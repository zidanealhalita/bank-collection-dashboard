"""Uji integritas data dummy dan logika metrik/Markov."""
import numpy as np
import pandas as pd
import pytest

from src import config as C
from src import markov as MK
from src import metrics as M
from src.data import load_data


@pytest.fixture(scope="module")
def D():
    return load_data()


def test_files_exist():
    for p in C.DATA_FILES.values():
        assert p.exists()


def test_keys_unique(D):
    assert D["loans"]["loan_id"].is_unique
    assert D["assignments"]["assignment_id"].is_unique
    assert D["actions"]["action_id"].is_unique
    assert D["payments"]["payment_id"].is_unique
    assert D["collectors"]["collector_id"].is_unique


def test_referential_integrity(D):
    loans = set(D["loans"]["loan_id"])
    assert set(D["snapshots"]["loan_id"]) <= loans
    assert set(D["payments"]["loan_id"]) <= loans
    assert set(D["assignments"]["loan_id"]) <= loans
    asg = set(D["assignments"]["assignment_id"])
    assert set(D["actions"]["assignment_id"]) <= asg
    assert set(D["payments"]["assignment_id"].dropna()) <= asg
    cols = set(D["collectors"]["collector_id"])
    assert set(D["assignments"]["collector_id"]) <= cols
    assert set(D["actions"]["collector_id"]) <= cols


def test_no_nulls_in_core_columns(D):
    for t, cols in {
        "snapshots": ["loan_id", "snapshot_month", "bucket", "dpd", "outstanding"],
        "assignments": ["assignment_id", "collector_id", "team", "assigned_date", "cured"],
        "actions": ["action_id", "channel", "outcome", "action_date"],
        "loans": ["loan_id", "principal", "installment", "tenor", "vintage"],
    }.items():
        assert D[t][cols].notna().all().all(), t


def test_bucket_dpd_consistent(D):
    s = D["snapshots"]
    s = s[s["is_active"]]
    bounds = {"Current": (0, 0), "1-30": (1, 30), "31-60": (31, 60), "61-90": (61, 90), "90+": (91, 10_000)}
    for b, (lo, hi) in bounds.items():
        d = s.loc[s["bucket"] == b, "dpd"]
        assert d.between(lo, hi).all(), b


def test_snapshot_one_row_per_loan_month(D):
    assert not D["snapshots"].duplicated(["loan_id", "snapshot_month"]).any()


def test_terminal_states_once(D):
    s = D["snapshots"]
    term = s[s["bucket"].isin(["Closed", "Write-off"])]
    assert term["loan_id"].is_unique
    # tidak ada snapshot setelah status terminal
    last = s.groupby("loan_id")["snapshot_month"].max()
    t = term.set_index("loan_id")["snapshot_month"]
    assert (last.loc[t.index] == t).all()


def test_amounts_sane(D):
    s = D["snapshots"]
    assert (s["outstanding"] >= 0).all()
    assert (D["payments"]["amount"] > 0).all()
    a = D["assignments"]
    assert (a["collected_amount"] <= a["amount_due"] + 1).all()
    assert (a["amount_due"] > 0).all()


def test_actions_within_assignment_month(D):
    a = D["assignments"][["assignment_id", "month", "assigned_date"]]
    x = D["actions"].merge(a, on="assignment_id")
    assert (x["action_date"].dt.strftime("%Y-%m") == x["month"]).all()
    first = x.groupby("assignment_id")["action_date"].min()
    chk = a.set_index("assignment_id")["assigned_date"]
    assert (first == chk.loc[first.index]).all()


def test_ptp_logic(D):
    x = D["actions"]
    p = x[x["ptp_flag"]]
    assert p["ptp_kept"].notna().all()
    assert (p["ptp_date"] >= p["action_date"]).all()
    assert x.loc[~x["ptp_flag"], "ptp_kept"].isna().all()


def test_cure_implies_collected(D):
    a = D["assignments"]
    assert (a.loc[a["cured"], "collected_amount"] > 0).all()
    assert (a.loc[a["cured"], "collected_amount"] >= a.loc[a["cured"], "amount_due"] * 0.999).all()


def test_roll_matrix_rows_sum_to_one(D):
    prob, raw = MK.roll_matrix(D["pairs"], "count")
    assert np.allclose(prob.sum(axis=1), 1.0)
    P = MK.full_matrix(prob)
    assert np.allclose(P.sum(axis=1), 1.0)
    prob2, _ = MK.roll_matrix(D["pairs"], "outstanding")
    assert np.allclose(prob2.sum(axis=1), 1.0)


def test_pairs_match_snapshots(D):
    s = D["snapshots"]
    n_active_rows = s["is_active"].sum()
    # setiap baris aktif yang bukan snapshot terakhir bulan data punya tepat satu pasangan
    last_month = s["snapshot_month"].max()
    expected = ((s["is_active"]) & (s["snapshot_month"] != last_month)).sum()
    assert len(D["pairs"]) == expected


def test_markov_projection_conserves_mass(D):
    prob, _ = MK.roll_matrix(D["pairs"], "count")
    P = MK.full_matrix(prob)
    v0 = np.array([100, 20, 10, 5, 5, 0, 0.0])
    path = MK.project(P, v0, 12)
    assert np.allclose(path.sum(axis=1), v0.sum())
    # absorbing mass tidak pernah turun
    assert (np.diff(path[:, -1]) >= -1e-9).all()
    assert (np.diff(path[:, -2]) >= -1e-9).all()


def test_absorption_probabilities(D):
    prob, _ = MK.roll_matrix(D["pairs"], "count")
    ab = MK.absorption(MK.full_matrix(prob))
    assert np.allclose(ab["P(akhirnya lunas)"] + ab["P(akhirnya write-off)"], 1.0)
    # makin dalam bucket, makin tinggi peluang write-off
    assert ab["P(akhirnya write-off)"].is_monotonic_increasing


def test_stress_matrix(D):
    prob, _ = MK.roll_matrix(D["pairs"], "count")
    P = MK.full_matrix(prob)
    S = MK.stress_matrix(P, 1.5)
    assert np.allclose(S.sum(axis=1), 1.0)
    assert S[1, 2] > P[1, 2]  # roll-forward naik
    assert np.allclose(MK.stress_matrix(P, 1.0), P)


def test_vintage_monotone(D):
    for metric in M.EVER_SETS:
        c = M.vintage_curves(D["snapshots"], D["loans"], metric)
        for _, row in c.iterrows():
            v = row.dropna().to_numpy()
            assert (np.diff(v) >= -1e-9).all(), metric
            assert (v <= 100 + 1e-9).all()


def test_vintage_ordering(D):
    c = M.vintage_curves(D["snapshots"], D["loans"], "Ever 90+ DPD")
    # vintage longgar (Okt 2025) harus lebih buruk dari vintage ketat (Jan 2026) pada MOB sama
    assert c.loc["2025-09", 6] > c.loc["2026-01", 6]


def test_scorecard_and_composite(D):
    sc = M.scorecard(D["assignments"], D["actions"], ["collector_id", "collector_name", "team"])
    assert len(sc) == len(D["collectors"])
    for c in ("Cure rate", "Recovery rate", "PTP kept rate", "Contact rate"):
        assert sc[c].between(0, 1).all(), c
    assert sc["Akun"].sum() == len(D["assignments"])
    sc = M.add_composite(sc, "team")
    assert sc["Skor"].between(0, 100).all()
    assert (sc.groupby("team")["Peringkat di tim"].min() == 1).all()


def test_skill_signal_exists(D):
    """Collector dalam tim yang sama harus menunjukkan variasi cure rate yang bermakna."""
    sc = M.scorecard(D["assignments"], D["actions"], ["collector_id", "team"])
    spread = sc.groupby("team")["Cure rate"].agg(lambda s: s.max() - s.min())
    assert (spread > 0.03).all()


def test_backtest_runs(D):
    res = MK.backtest(D["pairs"], D["snapshots"], "2026-07", 3, "count")
    assert res is not None
    cmp_tbl, path = res
    assert np.isclose(cmp_tbl["Proyeksi"].sum(), 100) and np.isclose(cmp_tbl["Realisasi"].sum(), 100)


def test_absorption_undefined_on_empty_rows(D):
    one = D["pairs"][D["pairs"]["from_month"] == "2025-02"]  # hanya Current & 1-30 yang punya observasi
    prob, raw = MK.roll_matrix(one, "count")
    assert MK.absorption(MK.full_matrix(prob)) is None
    assert "90+" in MK.thin_rows(raw)
