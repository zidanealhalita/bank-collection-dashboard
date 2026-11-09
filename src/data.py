"""Loader data (dengan cache Streamlit) + fallback generate otomatis bila Parquet belum ada."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import config as C

ACTIVE_CAT = pd.CategoricalDtype(C.BUCKETS, ordered=True)


def _ensure_files() -> None:
    if all(p.exists() for p in C.DATA_FILES.values()):
        return
    from .gen_sim import simulate  # impor lambat: hanya dipakai bila perlu

    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in simulate(C.SEED).items():
        df.to_parquet(C.DATA_FILES[name], index=False)


def build_transition_pairs(snap: pd.DataFrame) -> pd.DataFrame:
    """Pasangan (bucket bulan t -> status bulan t+1) per pinjaman. Basis roll rate & Markov."""
    cols = ["loan_id", "snapshot_month", "bucket", "outstanding"]
    s = snap.loc[:, cols].copy()
    s["bucket"] = s["bucket"].astype(str)
    s = s.sort_values(["loan_id", "snapshot_month"], kind="stable")
    g = s.groupby("loan_id", sort=False)
    s["to_bucket"] = g["bucket"].shift(-1)
    s["to_month"] = g["snapshot_month"].shift(-1)
    pairs = s.dropna(subset=["to_bucket"]).rename(
        columns={"snapshot_month": "from_month", "bucket": "from_bucket", "outstanding": "from_outstanding"}
    )
    pairs = pairs[pairs["from_bucket"].isin(C.BUCKETS)]
    return pairs.reset_index(drop=True)


@st.cache_data(show_spinner="Memuat data portofolio...")
def load_data() -> dict[str, pd.DataFrame]:
    _ensure_files()
    t = {k: pd.read_parquet(p) for k, p in C.DATA_FILES.items()}

    loans, snap, pays, asg, act, col = (
        t["loans"], t["snapshots"], t["payments"], t["assignments"], t["actions"], t["collectors"],
    )
    loan_attr = loans[["loan_id", "vintage", "product", "risk_band", "region", "income_band", "principal", "tenor"]]

    snap = snap.copy()
    snap["bucket"] = snap["bucket"].astype(str)
    snap = snap.merge(loan_attr, on="loan_id", how="left")
    snap["is_active"] = snap["bucket"].isin(C.BUCKETS)

    pairs = build_transition_pairs(snap)
    pairs = pairs.merge(loan_attr[["loan_id", "product", "risk_band", "vintage"]], on="loan_id", how="left")

    asg = asg.merge(col[["collector_id", "collector_name"]], on="collector_id", how="left")
    asg = asg.merge(loan_attr[["loan_id", "product", "risk_band", "vintage"]], on="loan_id", how="left")
    asg["assigned_date"] = pd.to_datetime(asg["assigned_date"])

    act = act.merge(col[["collector_id", "collector_name"]], on="collector_id", how="left")
    act["action_date"] = pd.to_datetime(act["action_date"])
    act["ptp_kept"] = act["ptp_kept"].astype("object")

    return {
        "loans": loans, "snapshots": snap, "payments": pays, "assignments": asg,
        "actions": act, "collectors": col, "pairs": pairs,
    }


def month_labels(months: list[str]) -> dict[str, str]:
    """'2026-03' -> 'Mar 2026' (singkatan Indonesia)."""
    names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    return {m: f"{names[int(m[5:7]) - 1]} {m[:4]}" for m in months}
