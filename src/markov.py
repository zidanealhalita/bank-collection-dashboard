"""Roll rate = matriks transisi Markov. Estimasi, proyeksi, absorpsi, stress, dan backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

# Ruang keadaan: 5 bucket aktif + 2 keadaan absorbing (pelunasan & write-off)
STATES = C.BUCKETS + ["Closed", "Write-off"]
STATE_LABEL = {**{b: b for b in C.BUCKETS}, "Closed": "Lunas", "Write-off": "Write-off"}
N = len(STATES)
NA = len(C.BUCKETS)


def roll_matrix(pairs: pd.DataFrame, weight: str = "count") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (probabilitas baris-ternormalisasi 5x7, bobot mentah 5x7)."""
    if pairs.empty:
        z = pd.DataFrame(0.0, index=C.BUCKETS, columns=STATES)
        return z, z.copy()
    w = np.ones(len(pairs)) if weight == "count" else pairs["from_outstanding"].to_numpy()
    raw = (
        pairs.assign(_w=w)
        .pivot_table(index="from_bucket", columns="to_bucket", values="_w", aggfunc="sum", fill_value=0.0)
        .reindex(index=C.BUCKETS, columns=STATES, fill_value=0.0)
    )
    tot = raw.sum(axis=1).replace(0, np.nan)
    prob = raw.div(tot, axis=0).fillna(0.0)
    return prob, raw


def full_matrix(prob: pd.DataFrame) -> np.ndarray:
    """Lengkapi menjadi 7x7 dengan dua baris absorbing."""
    P = np.zeros((N, N))
    P[:NA, :] = prob.to_numpy()
    # baris tanpa observasi dianggap tetap di bucketnya
    for i in range(NA):
        if P[i].sum() == 0:
            P[i, i] = 1.0
    P[NA, NA] = 1.0
    P[NA + 1, NA + 1] = 1.0
    return P


def stress_matrix(P: np.ndarray, factor: float) -> np.ndarray:
    """Kalikan peluang 'memburuk' (naik bucket / write-off) dengan `factor`, lalu normalisasi ulang."""
    if abs(factor - 1.0) < 1e-9:
        return P.copy()
    S = P.copy()
    for i in range(NA):
        worse = [j for j in range(N) if (j > i and j < NA) or j == N - 1]
        S[i, worse] *= factor
        S[i] /= S[i].sum()
    return S


def project(P: np.ndarray, v0: np.ndarray, steps: int) -> np.ndarray:
    """Distribusi keadaan (steps+1, 7): v_t = v_0 P^t."""
    out = np.zeros((steps + 1, N))
    v = v0.astype(float).copy()
    out[0] = v
    for t in range(1, steps + 1):
        v = v @ P
        out[t] = v
    return out


def absorption(P: np.ndarray) -> pd.DataFrame | None:
    """Analisis rantai absorbing via matriks fundamental N = (I-Q)^-1.

    Return peluang akhir lunas vs write-off dan ekspektasi lama (bulan) sampai absorpsi.
    Return None bila tidak terdefinisi (mis. ada bucket tanpa observasi sehingga tidak pernah keluar).
    """
    Q = P[:NA, :NA]
    R = P[:NA, NA:]
    try:
        if np.max(np.abs(np.linalg.eigvals(Q))) >= 1 - 1e-9:
            return None
        fund = np.linalg.inv(np.eye(NA) - Q)
    except np.linalg.LinAlgError:
        return None
    B = fund @ R
    t_abs = fund.sum(axis=1)
    return pd.DataFrame(
        {
            "P(akhirnya lunas)": B[:, 0],
            "P(akhirnya write-off)": B[:, 1],
            "Ekspektasi bulan sampai selesai": t_abs,
        },
        index=C.BUCKETS,
    )


def thin_rows(raw: pd.DataFrame, min_obs: float = 30) -> list[str]:
    """Bucket yang observasinya terlalu sedikit untuk estimasi baris matriks yang andal (hanya basis count)."""
    s = raw.sum(axis=1)
    return [b for b in C.BUCKETS if s[b] < min_obs]


def state_vector(snap_month: pd.DataFrame, weight: str = "count") -> np.ndarray:
    """Vektor awal (7,) dari snapshot satu bulan (hanya bucket aktif)."""
    act = snap_month[snap_month["bucket"].isin(C.BUCKETS)]
    if weight == "count":
        s = act.groupby("bucket").size()
    else:
        s = act.groupby("bucket")["outstanding"].sum()
    v = np.zeros(N)
    for i, b in enumerate(C.BUCKETS):
        v[i] = float(s.get(b, 0.0))
    return v


def backtest(
    pairs: pd.DataFrame, snap: pd.DataFrame, origin: str, horizon: int, weight: str = "count"
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Estimasi matriks hanya dari transisi sebelum `origin`, proyeksikan `horizon` bulan ke depan
    dari kohort pinjaman aktif pada `origin`, bandingkan dengan realisasi kohort yang sama.

    Return (tabel perbandingan pada akhir horizon, tabel lintasan per bulan) atau None bila data tidak cukup.
    """
    months = sorted(snap["snapshot_month"].unique())
    if origin not in months:
        return None
    k = months.index(origin) + horizon
    if k >= len(months):
        return None
    target = months[k]

    train = pairs[pairs["from_month"] < origin]
    if len(train) < 500:
        return None
    prob, _ = roll_matrix(train, weight)
    P = full_matrix(prob)

    cohort = snap[(snap["snapshot_month"] == origin) & snap["bucket"].isin(C.BUCKETS)]
    ids = set(cohort["loan_id"])
    v0 = state_vector(cohort, weight)
    proj = project(P, v0, horizon)

    sub = snap[snap["loan_id"].isin(ids)].sort_values(["loan_id", "snapshot_month"])
    ids_arr = cohort["loan_id"].to_numpy()
    wvec = np.ones(len(cohort)) if weight == "count" else cohort["outstanding"].to_numpy()
    last = sub.groupby("loan_id")["bucket"].last().reindex(ids_arr)
    actual = np.zeros((horizon + 1, N))
    actual[0] = v0
    for h in range(1, horizon + 1):
        mh = months[months.index(origin) + h]
        at = sub[sub["snapshot_month"] == mh].set_index("loan_id")["bucket"].reindex(ids_arr)
        cur_state = at.where(at.notna(), last).to_numpy()
        for j, s in enumerate(STATES):
            actual[h, j] = wvec[cur_state == s].sum()

    # bobot realisasi bucket aktif memakai bobot awal (bukan outstanding saat itu) agar sebanding dgn proyeksi
    cmp_tbl = pd.DataFrame(
        {
            "Proyeksi": proj[-1] / proj[-1].sum() * 100,
            "Realisasi": actual[-1] / actual[-1].sum() * 100,
        },
        index=[STATE_LABEL[s] for s in STATES],
    )
    cmp_tbl["Selisih (pp)"] = cmp_tbl["Proyeksi"] - cmp_tbl["Realisasi"]

    path = []
    for h in range(horizon + 1):
        for j, s in enumerate(STATES):
            path.append(
                {
                    "bulan_ke": h,
                    "state": STATE_LABEL[s],
                    "Proyeksi": proj[h, j] / proj[h].sum() * 100,
                    "Realisasi": actual[h, j] / actual[h].sum() * 100,
                }
            )
    return cmp_tbl, pd.DataFrame(path)
