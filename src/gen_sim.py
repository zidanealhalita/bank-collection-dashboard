"""Generator bagian 2: simulasi bulanan (rantai Markov per pinjaman) + aktivitas penagihan.

Ide inti
--------
* Setiap pinjaman bergerak antar bucket tiap akhir bulan mengikuti matriks transisi dasar `P0`
  yang di-"tilt" secara eksponensial oleh kualitas peminjam (risk band, produk, vintage, makro)
  dan, untuk akun yang ditagih, oleh kualitas collector + efektivitas channel.
* Jumlah cicilan tunggakan (`arr`) dan cicilan terbayar (`paid_inst`) dijaga konsisten, sehingga
  pembayaran, outstanding, write-off, dan pelunasan semuanya turunan dari lintasan bucket.
* Aksi penagihan (SMS/WA/Call/Field Visit) dibangkitkan SETELAH hasil bulan diketahui dan
  dikondisikan pada hasil tersebut (mis. akun yang cure pasti punya aksi "kunci" yang berhasil).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .gen_loans import make_collectors, make_loans

STATE_LABELS = np.array(C.BUCKETS + ["Write-off", "Closed"], dtype=object)  # kode 0..6

# -- matriks transisi dasar: baris = bucket asal (0..4), kolom = tujuan (0..4, Write-off)
P0 = np.array(
    [
        [0.960, 0.040, 0.0, 0.0, 0.0, 0.0],
        [0.580, 0.170, 0.250, 0.0, 0.0, 0.0],
        [0.220, 0.140, 0.140, 0.500, 0.0, 0.0],
        [0.080, 0.060, 0.060, 0.100, 0.700, 0.0],
        [0.020, 0.010, 0.010, 0.020, 0.940, 0.0],
    ]
)
WO_BASE = 0.30  # peluang tambahan write-off bila sudah >= 2 bulan di 90+
# K[s, j] = jumlah "langkah perbaikan" dari s ke j (positif = membaik)
K = np.array([[s - j for j in range(6)] for s in range(5)], dtype=float)
K[:, 5] = np.arange(5) - 6.0

BAND_Q = np.array([0.55, 0.0, -0.50])
PROD_Q = np.array([0.0, -0.15, 0.20])
MACRO_Q = {"2025-12": -0.10, "2026-01": -0.10, "2026-03": -0.20, "2026-04": -0.35, "2026-05": -0.20}

CH_IDX = {c: i for i, c in enumerate(C.CHANNELS)}
CH_EFF = np.array([C.CHANNEL_EFFECT[c] for c in C.CHANNELS])
CH_COST = np.array([350, 700, 3500, 75000])
P_NO_CONTACT = np.array([0.80, 0.62, 0.58, 0.35])
TEAM_OF_STATE = {1: 0, 2: 1, 3: 2, 4: 2}
ATT_OPTS = {
    0: ([2, 3, 4], [0.30, 0.45, 0.25]),
    1: ([3, 4, 5], [0.30, 0.45, 0.25]),
    2: ([3, 4, 5, 6], [0.20, 0.35, 0.30, 0.15]),
}
MAX_ATT = 6
OUTCOME_NAMES = np.array(C.OUTCOMES, dtype=object)  # 0 NoContact,1 NoCommit,2 Refused,3 PTP,4 PaidImm


def _dpd_for(s: np.ndarray, m90_new: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    lo = np.array([0, 1, 31, 61, 91])[np.minimum(s, 4)]
    hi = np.array([0, 30, 60, 90, 120])[np.minimum(s, 4)]
    dpd = rng.integers(lo, hi + 1)
    in90 = s == 4
    dpd = np.where(in90, 91 + 30 * np.maximum(m90_new - 1, 0) + rng.integers(0, 30, len(s)), dpd)
    return dpd


def simulate(seed: int = C.SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    collectors = make_collectors(rng)
    loans, v_eff = make_loans(rng)
    n = len(loans)

    months = pd.period_range(C.FIRST_VINTAGE, C.LAST_SNAPSHOT, freq="M")
    T = len(months)
    v_idx = loans["vintage_idx"].to_numpy()
    band = loans["band_idx"].to_numpy()
    prod = loans["product"].map({p: i for i, p in enumerate(C.PRODUCTS)}).to_numpy()
    tenor = loans["tenor"].to_numpy()
    principal = loans["principal"].to_numpy()
    inst = loans["installment"].to_numpy()
    due_day = loans["due_day"].to_numpy()

    # ---- struktur collector
    skill = collectors["skill"].to_numpy()
    team_cols, team_w = [], []
    for team in C.TEAMS:
        ids = np.where(collectors["team"].to_numpy() == team)[0]
        w = collectors["capacity_weight"].to_numpy()[ids]
        team_cols.append(ids)
        team_w.append(w / w.sum())
    team_ch_w = [np.array([C.TEAM_CHANNEL_WEIGHTS[t][c] for c in C.CHANNELS]) for t in C.TEAMS]
    col_ids = collectors["collector_id"].to_numpy()
    col_team = collectors["team"].to_numpy()

    # ---- state per pinjaman
    state = np.full(n, -1)            # -1 belum cair, 0..4 aktif, 9 tidak aktif
    arr = np.zeros(n, dtype=int)      # jumlah cicilan tunggakan
    paid_inst = np.zeros(n, dtype=int)
    m90 = np.zeros(n, dtype=int)      # bulan berturut-turut di 90+
    dpd_now = np.zeros(n, dtype=int)

    snaps, assigns, actions, pays = [], [], [], []
    aid_counter = 0

    for t in range(T):
        m_start = months[t].start_time
        m_end = months[t].end_time.normalize()
        ndays = m_end.day
        snap_date = np.datetime64(m_end.date())
        mkey = str(months[t])

        # ----------------------------------------------------- pinjaman aktif yang melangkah
        cur = np.where((v_idx < t) & (state >= 0) & (state <= 4))[0]
        m = len(cur)
        if m:
            s_prev = state[cur]
            mob = t - v_idx[cur]
            due_new = (mob <= tenor[cur]).astype(int)
            a_prev = arr[cur]
            assigned = s_prev >= 1
            A = int(assigned.sum())

            # tilt kualitas (positif = lebih baik)
            q = BAND_Q[band[cur]] + PROD_Q[prod[cur]] - v_eff[v_idx[cur]] + MACRO_Q.get(mkey, 0.0)
            q = q - np.where((s_prev == 0) & (mob <= 3), 0.30, 0.0)
            q = q + np.where((s_prev == 0) & (mob > 6), 0.10, 0.0)

            # ----------------------------------------------- penugasan & channel
            if A:
                a_idx = np.where(assigned)[0]
                a_state = s_prev[a_idx]
                a_team = np.array([TEAM_OF_STATE[s] for s in a_state])
                col = np.zeros(A, dtype=int)
                for k in range(3):
                    sel = a_team == k
                    if sel.any():
                        col[sel] = rng.choice(team_cols[k], size=sel.sum(), p=team_w[k])
                n_att = np.zeros(A, dtype=int)
                ch = np.zeros((A, MAX_ATT), dtype=int)
                for k in range(3):
                    sel = np.where(a_team == k)[0]
                    if not len(sel):
                        continue
                    opts, pr = ATT_OPTS[k]
                    n_att[sel] = rng.choice(opts, size=len(sel), p=pr)
                    prim = rng.choice(4, size=len(sel), p=team_ch_w[k])
                    alt = rng.choice(4, size=(len(sel), MAX_ATT), p=team_ch_w[k])
                    same = rng.random((len(sel), MAX_ATT)) < 0.55
                    block = np.where(same, prim[:, None], alt)
                    block[:, 0] = prim
                    ch[sel] = block
                mask = np.arange(MAX_ATT)[None, :] < n_att[:, None]
                effort = (CH_EFF[ch] * mask).sum(1) / n_att
                q[a_idx] += skill[col] + effort

            # ----------------------------------------------- sampling transisi
            P = P0[s_prev].copy()
            elig = (s_prev == 4) & (m90[cur] >= 2)
            P[elig, 5] = WO_BASE
            P = P * np.exp(q[:, None] * K[s_prev])
            P = P / P.sum(1, keepdims=True)
            cum = P.cumsum(1)
            u = rng.random(m)[:, None]
            s_new = (u >= cum[:, :-1]).sum(1)
            s_new = np.where(~elig & (s_new == 5), s_prev, s_new)

            # ----------------------------------------------- pembayaran & ledger
            avail = a_prev + due_new
            wo = s_new == 5
            b = np.minimum(s_new, 4)
            paid = np.where(b < 4, np.maximum(0, avail - b), 0)
            in90 = (b == 4) & ~wo
            partial = in90 & (s_prev == 4) & (avail - 1 >= 1) & (rng.random(m) < 0.20)
            paid = np.where(partial, 1, paid)
            paid = np.where(wo, 0, paid)
            arr_new = avail - paid
            paid_new = paid_inst[cur] + paid
            closed = (paid_new >= tenor[cur]) & ~wo
            m90_prev = np.where(s_prev == 4, m90[cur], 0)
            m90_new = np.where(in90, m90_prev + 1, 0)
            outstanding = np.maximum(0.0, principal[cur] * (1 - paid_new / tenor[cur]))

            code = np.where(closed, 6, np.where(wo, 5, b))
            dpd_new = np.where(code <= 4, _dpd_for(np.minimum(code, 4), m90_new, rng), 0)
            dpd_new = np.where(code >= 5, 0, dpd_new)

            snap_due = np.where(
                code == 0,
                snap_date + due_day[cur].astype("timedelta64[D]"),
                np.where(code <= 4, snap_date - dpd_new.astype("timedelta64[D]"), np.datetime64("NaT")),
            )
            snaps.append(
                pd.DataFrame(
                    {
                        "snapshot_month": mkey,
                        "snapshot_date": pd.Timestamp(snap_date),
                        "loan_idx": cur,
                        "mob": mob,
                        "bucket": STATE_LABELS[code],
                        "dpd": dpd_new,
                        "due_date": snap_due,
                        "installments_overdue": np.where(code <= 4, arr_new, 0),
                        "outstanding": np.where(code >= 5, 0.0, outstanding).round(0),
                        "overdue_amount": np.where(code <= 4, arr_new * inst[cur], 0).astype(float),
                        "writeoff_amount": np.where(code == 5, outstanding, 0.0).round(0),
                    }
                )
            )

            # ----------------------------------------------- pembayaran reguler (akun Current)
            reg = (s_prev == 0) & (paid > 0)
            if reg.any():
                d = due_day[cur[reg]] - 1 - rng.choice([0, 0, 0, 1, 2, 3], size=reg.sum())
                d = np.clip(d, 0, ndays - 1)
                pays.append(
                    pd.DataFrame(
                        {
                            "loan_idx": cur[reg],
                            "payment_date": m_start + pd.to_timedelta(d, unit="D"),
                            "amount": (paid[reg] * inst[cur[reg]]).astype(float),
                            "payment_type": "Regular",
                            "assignment_id": None,
                            "channel": None,
                        }
                    )
                )

            # ----------------------------------------------- assignment + aksi penagihan
            if A:
                loan_a = cur[a_idx]
                paid_a = paid[a_idx]
                amount_due = avail[a_idx] * inst[loan_a]
                collected = paid_a * inst[loan_a]
                s_new_a = s_new[a_idx]
                closed_a = closed[a_idx]
                cured = (s_new_a == 0) | closed_a
                improved = (s_new_a < a_state) | closed_a
                pay_mask = paid_a > 0

                # tanggal aksi
                day0 = rng.integers(1, 11, A)
                gaps = rng.integers(2, 6, (A, MAX_ATT))
                gaps[:, 0] = 0
                days = np.minimum(day0[:, None] + gaps.cumsum(1), max(ndays - 3, 5))
                # outcome dasar
                u1 = rng.random((A, MAX_ATT))
                u2 = rng.random((A, MAX_ATT))
                contacted = u1 >= P_NO_CONTACT[ch]
                out = np.where(~contacted, 0, np.where(u2 < 0.55, 1, np.where(u2 < 0.75, 2, 3)))
                kept = np.zeros((A, MAX_ATT), dtype=bool)
                # aksi kunci untuk akun yang membayar
                w = np.exp(3.0 * CH_EFF[ch]) * (1 + 0.3 * np.arange(MAX_ATT))[None, :] * mask
                pk = w / w.sum(1, keepdims=True)
                key = (rng.random(A)[:, None] >= pk.cumsum(1)[:, :-1]).sum(1)
                key = np.minimum(key, n_att - 1)
                rows = np.arange(A)
                is_ptp = rng.random(A) < 0.68
                key_out = np.where(is_ptp, 3, 4)
                out[rows[pay_mask], key[pay_mask]] = key_out[pay_mask]
                kept[rows[pay_mask], key[pay_mask]] = is_ptp[pay_mask]
                mask2 = mask & ((~pay_mask)[:, None] | (np.arange(MAX_ATT)[None, :] <= key[:, None]))

                ptp_gap = rng.integers(1, 6, (A, MAX_ATT))
                ptp_day = np.minimum(days + ptp_gap, ndays)
                a_ids = aid_counter + np.arange(A)
                first_date = m_start + pd.to_timedelta(days[:, 0] - 1, unit="D")

                # tanggal & jumlah pembayaran
                key_day = days[rows, key]
                key_ptp = ptp_day[rows, key]
                pay_day = np.where(is_ptp, np.maximum(key_day, key_ptp - rng.integers(0, 2, A)), key_day)
                pay_ch = ch[rows, key]
                pays.append(
                    pd.DataFrame(
                        {
                            "loan_idx": loan_a[pay_mask],
                            "payment_date": m_start + pd.to_timedelta(pay_day[pay_mask] - 1, unit="D"),
                            "amount": collected[pay_mask].astype(float),
                            "payment_type": "Collection",
                            "assignment_id": [f"AS{x:07d}" for x in a_ids[pay_mask]],
                            "channel": np.array(C.CHANNELS, dtype=object)[pay_ch[pay_mask]],
                        }
                    )
                )

                assigns.append(
                    pd.DataFrame(
                        {
                            "assignment_id": [f"AS{x:07d}" for x in a_ids],
                            "loan_idx": loan_a,
                            "month": mkey,
                            "assigned_date": first_date,
                            "collector_idx": col,
                            "primary_channel": np.array(C.CHANNELS, dtype=object)[ch[:, 0]],
                            "bucket_start": STATE_LABELS[a_state],
                            "dpd_start": dpd_now[loan_a],
                            "bucket_end": STATE_LABELS[code[a_idx]],
                            "amount_due": amount_due.astype(float),
                            "collected_amount": collected.astype(float),
                            "n_attempts": mask2.sum(1),
                            "cured": cured,
                            "improved": improved & ~cured,
                            "rolled_worse": s_new_a > a_state,
                        }
                    )
                )

                ai, aj = np.nonzero(mask2)
                ptp_flag = out[ai, aj] == 3
                ptp_date = m_start + pd.to_timedelta(ptp_day[ai, aj] - 1, unit="D")
                ptp_amt = np.where(
                    kept[ai, aj],
                    collected[ai],
                    (amount_due[ai] * rng.uniform(0.5, 1.0, len(ai)) / 1000).round() * 1000,
                )
                actions.append(
                    pd.DataFrame(
                        {
                            "assignment_id": [f"AS{x:07d}" for x in a_ids[ai]],
                            "loan_idx": loan_a[ai],
                            "collector_idx": col[ai],
                            "action_date": m_start + pd.to_timedelta(days[ai, aj] - 1, unit="D"),
                            "attempt_no": aj + 1,
                            "channel": np.array(C.CHANNELS, dtype=object)[ch[ai, aj]],
                            "outcome": OUTCOME_NAMES[out[ai, aj]],
                            "contact_made": out[ai, aj] != 0,
                            "ptp_flag": ptp_flag,
                            "ptp_date": pd.Series(ptp_date).where(ptp_flag, pd.NaT).to_numpy(),
                            "ptp_amount": np.where(ptp_flag, ptp_amt, np.nan),
                            "ptp_kept": pd.array(np.where(ptp_flag, kept[ai, aj], pd.NA), dtype="boolean"),
                            "cost": CH_COST[ch[ai, aj]].astype(float),
                        }
                    )
                )
                aid_counter += A

            # ----------------------------------------------- update state
            state[cur] = np.where(wo | closed, 9, b)
            arr[cur] = arr_new
            paid_inst[cur] = paid_new
            m90[cur] = m90_new
            dpd_now[cur] = dpd_new

        # ----------------------------------------------------- pinjaman baru bulan ini
        new = np.where(v_idx == t)[0]
        if len(new):
            state[new] = 0
            dpd_now[new] = 0
            snaps.append(
                pd.DataFrame(
                    {
                        "snapshot_month": mkey,
                        "snapshot_date": pd.Timestamp(snap_date),
                        "loan_idx": new,
                        "mob": 0,
                        "bucket": "Current",
                        "dpd": 0,
                        "due_date": snap_date + due_day[new].astype("timedelta64[D]"),
                        "installments_overdue": 0,
                        "outstanding": principal[new].astype(float),
                        "overdue_amount": 0.0,
                        "writeoff_amount": 0.0,
                    }
                )
            )

    return _finalize(loans, collectors, snaps, assigns, actions, pays)


def _finalize(loans, collectors, snaps, assigns, actions, pays) -> dict[str, pd.DataFrame]:
    loan_ids = loans["loan_id"].to_numpy()
    col_ids = collectors["collector_id"].to_numpy()

    snapshots = pd.concat(snaps, ignore_index=True)
    snapshots["loan_id"] = loan_ids[snapshots.pop("loan_idx").to_numpy()]
    snapshots["due_date"] = pd.to_datetime(snapshots["due_date"])
    for c in ("mob", "dpd", "installments_overdue"):
        snapshots[c] = snapshots[c].astype("int32")
    snapshots["bucket"] = snapshots["bucket"].astype("category")

    assignments = pd.concat(assigns, ignore_index=True)
    assignments["loan_id"] = loan_ids[assignments.pop("loan_idx").to_numpy()]
    cidx = assignments.pop("collector_idx").to_numpy()
    assignments["collector_id"] = col_ids[cidx]
    assignments["team"] = collectors["team"].to_numpy()[cidx]
    assignments = assignments[
        ["assignment_id", "loan_id", "month", "assigned_date", "collector_id", "team", "primary_channel",
         "bucket_start", "dpd_start", "bucket_end", "amount_due", "collected_amount", "n_attempts",
         "cured", "improved", "rolled_worse"]
    ]

    act = pd.concat(actions, ignore_index=True)
    act["loan_id"] = loan_ids[act.pop("loan_idx").to_numpy()]
    cidx = act.pop("collector_idx").to_numpy()
    act["collector_id"] = col_ids[cidx]
    act["team"] = collectors["team"].to_numpy()[cidx]
    act.insert(0, "action_id", [f"AC{i + 1:08d}" for i in range(len(act))])
    act["ptp_date"] = pd.to_datetime(act["ptp_date"])
    act = act[
        ["action_id", "assignment_id", "loan_id", "collector_id", "team", "action_date", "attempt_no",
         "channel", "outcome", "contact_made", "ptp_flag", "ptp_date", "ptp_amount", "ptp_kept", "cost"]
    ]

    payments = pd.concat(pays, ignore_index=True)
    payments["loan_id"] = loan_ids[payments.pop("loan_idx").to_numpy()]
    payments = payments.sort_values("payment_date", kind="stable").reset_index(drop=True)
    payments.insert(0, "payment_id", [f"PY{i + 1:08d}" for i in range(len(payments))])
    payments = payments[["payment_id", "loan_id", "payment_date", "amount", "payment_type", "assignment_id", "channel"]]

    loans_out = loans.drop(columns=["vintage_idx", "band_idx"]).copy()
    cols_out = collectors.drop(columns=["skill", "capacity_weight"]).copy()
    return {
        "loans": loans_out,
        "snapshots": snapshots,
        "payments": payments,
        "assignments": assignments,
        "actions": act,
        "collectors": cols_out,
    }
