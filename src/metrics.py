"""Fungsi metrik murni pandas (tanpa Streamlit) agar mudah diuji."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

# ------------------------------------------------------------------ aging


def aging_by_month(snap: pd.DataFrame, basis: str = "outstanding") -> pd.DataFrame:
    """Tabel bulan x bucket (nilai absolut) untuk pinjaman aktif."""
    act = snap[snap["bucket"].isin(C.BUCKETS)]
    if basis == "count":
        t = act.groupby(["snapshot_month", "bucket"]).size().unstack(fill_value=0)
    else:
        t = act.groupby(["snapshot_month", "bucket"])["outstanding"].sum().unstack(fill_value=0.0)
    return t.reindex(columns=C.BUCKETS, fill_value=0)


def portfolio_kpis(snap: pd.DataFrame, month: str) -> dict:
    """KPI portofolio pada akhir `month`, termasuk pembanding bulan sebelumnya."""

    def one(m: str) -> dict:
        a = snap[(snap["snapshot_month"] == m) & snap["bucket"].isin(C.BUCKETS)]
        tot = a["outstanding"].sum()
        by = a.groupby("bucket")["outstanding"].sum().reindex(C.BUCKETS, fill_value=0.0)
        wo = snap[(snap["snapshot_month"] == m) & (snap["bucket"] == "Write-off")]["writeoff_amount"].sum()
        return {
            "outstanding": tot,
            "loans": len(a),
            "dpd1": 1 - by["Current"] / tot if tot else 0.0,
            "dpd30": by[["31-60", "61-90", "90+"]].sum() / tot if tot else 0.0,
            "npl90": by["90+"] / tot if tot else 0.0,
            "writeoff": wo,
        }

    months = sorted(snap["snapshot_month"].unique())
    cur = one(month)
    i = months.index(month)
    prev = one(months[i - 1]) if i > 0 else None
    return {"cur": cur, "prev": prev}


# ------------------------------------------------------------------ vintage

EVER_SETS = {
    "Ever 30+ DPD": ["31-60", "61-90", "90+", "Write-off"],
    "Ever 60+ DPD": ["61-90", "90+", "Write-off"],
    "Ever 90+ DPD": ["90+", "Write-off"],
    "Kumulatif Write-off": ["Write-off"],
}


def vintage_curves(snap: pd.DataFrame, loans: pd.DataFrame, metric: str, basis: str = "count") -> pd.DataFrame:
    """Matriks vintage x MOB berisi % kumulatif pinjaman kohort yang pernah menyentuh `metric`.

    Penyebut = seluruh pinjaman kohort (termasuk yang sudah lunas), sehingga kurva tidak bias survivor.
    Sel di luar MOB yang teramati dibiarkan NaN (right-censoring).
    """
    hit = snap[snap["bucket"].isin(EVER_SETS[metric])]
    first = hit.groupby("loan_id")["mob"].min().rename("first_mob")
    d = loans[["loan_id", "vintage", "principal"]].merge(first, on="loan_id", how="left")
    d["w"] = 1.0 if basis == "count" else d["principal"].astype(float)

    last_m = pd.Period(snap["snapshot_month"].max(), freq="M")
    out = {}
    for v, g in d.groupby("vintage"):
        max_mob = (last_m - pd.Period(v, freq="M")).n
        tot = g["w"].sum()
        by_mob = g.dropna(subset=["first_mob"]).groupby("first_mob")["w"].sum()
        cum = by_mob.reindex(range(0, max_mob + 1), fill_value=0.0).cumsum() / tot * 100
        out[v] = cum
    return pd.DataFrame(out).T.sort_index()


def vintage_summary(snap: pd.DataFrame, loans: pd.DataFrame) -> pd.DataFrame:
    g = loans.groupby("vintage")
    t = pd.DataFrame(
        {
            "Pinjaman": g.size(),
            "Pencairan (Rp M)": g["principal"].sum() / 1e9,
            "Rata-rata plafon (Rp jt)": g["principal"].mean() / 1e6,
            "% Risk C": g["risk_band"].apply(lambda s: (s == C.RISK_BANDS[2]).mean() * 100),
        }
    )
    for name, mob in (("Ever 30+ @MOB3", 3), ("Ever 90+ @MOB6", 6)):
        metric = "Ever 30+ DPD" if "30+" in name else "Ever 90+ DPD"
        m = vintage_curves(snap, loans, metric)
        t[name + " (%)"] = m[mob] if mob in m.columns else np.nan
    return t


# ------------------------------------------------------------------ collector scorecard


def _assignment_metrics(g: pd.DataFrame) -> pd.Series:
    due = g["amount_due"].sum()
    return pd.Series(
        {
            "Akun": len(g),
            "Tagihan (Rp jt)": due / 1e6,
            "Tertagih (Rp jt)": g["collected_amount"].sum() / 1e6,
            "Cure rate": g["cured"].mean(),
            "Recovery rate": g["collected_amount"].sum() / due if due else np.nan,
            "Roll-worse rate": g["rolled_worse"].mean(),
        }
    )


def _action_metrics(a: pd.DataFrame) -> pd.Series:
    ptp = a[a["ptp_flag"]]
    kept = (ptp["ptp_kept"] == True).sum()  # noqa: E712 (kolom bertipe object berisi True/False/NA)
    return pd.Series(
        {
            "Aksi": len(a),
            "Contact rate": a["contact_made"].mean() if len(a) else np.nan,
            "PTP dibuat": len(ptp),
            "PTP kept rate": kept / len(ptp) if len(ptp) else np.nan,
            "Biaya (Rp jt)": a["cost"].sum() / 1e6,
        }
    )


def scorecard(asg: pd.DataFrame, act: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Scorecard per grup `by` (kolom ada di assignments; `act` sudah difilter pada assignment yang sama)."""
    if asg.empty:
        return pd.DataFrame()
    a = asg.groupby(by).apply(_assignment_metrics, include_groups=False)
    if not act.empty:
        keys = asg[["assignment_id"] + by].drop_duplicates("assignment_id")
        act2 = act.merge(keys, on="assignment_id", how="inner", suffixes=("", "_a"))
        b = act2.groupby(by).apply(_action_metrics, include_groups=False)
        a = a.join(b, how="left")
    a["Biaya per Rp1 jt tertagih"] = (a.get("Biaya (Rp jt)", 0) / a["Tertagih (Rp jt)"].replace(0, np.nan)) * 1.0
    return a.reset_index()


def add_composite(sc: pd.DataFrame, group_col: str = "team") -> pd.DataFrame:
    """Skor komposit 0-100 = rata-rata terbobot peringkat persentil DALAM tim (menghindari bias bucket)."""
    sc = sc.copy()
    w = {"Cure rate": 0.40, "Recovery rate": 0.35, "PTP kept rate": 0.25}
    parts = []
    for col, wt in w.items():
        parts.append(sc.groupby(group_col)[col].rank(pct=True).fillna(0.5) * wt)
    sc["Skor"] = sum(parts) * 100
    sc["Peringkat di tim"] = sc.groupby(group_col)["Skor"].rank(ascending=False, method="min").astype(int)
    team_avg = sc.groupby(group_col)["Cure rate"].transform("mean")
    sc["Cure vs rata-rata tim (pp)"] = (sc["Cure rate"] - team_avg) * 100
    return sc


def rating(score: float) -> str:
    if score >= 70:
        return "Top performer"
    if score >= 40:
        return "On track"
    return "Perlu coaching"


# ------------------------------------------------------------------ segmentasi risiko


def delinquency_by(snap_month: pd.DataFrame, dim: str) -> pd.DataFrame:
    a = snap_month[snap_month["bucket"].isin(C.BUCKETS)]
    t = a.groupby([dim, "bucket"])["outstanding"].sum().unstack(fill_value=0.0).reindex(columns=C.BUCKETS, fill_value=0.0)
    tot = t.sum(axis=1)
    out = pd.DataFrame(
        {
            "Outstanding (Rp M)": tot / 1e9,
            "DPD 1+ (%)": (1 - t["Current"] / tot) * 100,
            "DPD 30+ (%)": t[["31-60", "61-90", "90+"]].sum(axis=1) / tot * 100,
            "NPL 90+ (%)": t["90+"] / tot * 100,
        }
    )
    return out.reset_index()
