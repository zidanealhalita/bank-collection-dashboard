"""Generator bagian 1: master pinjaman dan master collector (data dummy)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

COLLECTOR_NAMES = [
    "Andi Pratama", "Siti Nurhaliza", "Budi Santoso", "Dewi Lestari", "Rizky Ramadhan",
    "Putri Anggraini", "Agus Setiawan", "Maya Sari", "Fajar Nugroho", "Rina Wulandari",
    "Dimas Saputra", "Intan Permata", "Hendra Wijaya", "Lia Kurniasih", "Yoga Prakoso",
    "Nadia Safitri", "Eko Susanto", "Ratna Dewi", "Bayu Aditya", "Citra Maharani",
    "Galih Firmansyah", "Wulan Purnama", "Irfan Hakim", "Sekar Ayu",
]


def make_collectors(rng: np.random.Generator) -> pd.DataFrame:
    """Buat master collector. Kolom `skill` (laten) dipakai simulasi lalu dibuang."""
    rows = []
    n = 0
    for team in C.TEAMS:
        prefix = team[0]
        size = C.TEAM_SIZE[team]
        skills = rng.normal(0.0, 0.20, size)
        # satu bintang dan satu yang lemah di tiap tim agar scorecard punya variasi nyata
        skills[rng.integers(0, size)] += 0.35
        skills[rng.integers(0, size)] -= 0.35
        for i in range(size):
            join = pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(rng.integers(-720, 360)))
            tenure_m = (pd.Timestamp("2026-10-31") - join).days / 30.4
            skill = skills[i] - (0.12 if tenure_m < 6 else 0.0)
            rows.append(
                {
                    "collector_id": f"COL-{prefix}{i + 1:02d}",
                    "collector_name": COLLECTOR_NAMES[n % len(COLLECTOR_NAMES)],
                    "team": team,
                    "join_date": join.normalize(),
                    "skill": float(skill),
                    "capacity_weight": float(rng.uniform(0.7, 1.3)),
                }
            )
            n += 1
    return pd.DataFrame(rows)


def _vintage_effects(months: pd.PeriodIndex) -> tuple[np.ndarray, np.ndarray]:
    """Return (peluang risk band C, efek logit vintage).

    Vintage Jul-Okt 2025 = kampanye pertumbuhan dengan underwriting longgar (kualitas buruk).
    Vintage 2026 = underwriting diperketat (kualitas membaik).
    """
    p_c = np.full(len(months), 0.19)
    eff = np.zeros(len(months))
    for i, m in enumerate(months):
        s = str(m)
        if "2025-07" <= s <= "2025-10":
            p_c[i], eff[i] = 0.36, 0.32
        elif s >= "2026-01":
            p_c[i], eff[i] = 0.14, -0.12
    return p_c, eff


def make_loans(rng: np.random.Generator) -> tuple[pd.DataFrame, np.ndarray]:
    """Return (loans_df, vintage_effect_per_vintage_index)."""
    months = pd.period_range(C.FIRST_VINTAGE, C.LAST_VINTAGE, freq="M")
    nm = len(months)
    w = np.linspace(1.0, 1.9, nm) * (1 + 0.12 * np.sin(np.arange(nm) * 0.9))
    w = w / w.sum()
    counts = rng.multinomial(C.N_LOANS, w)
    v_idx = np.repeat(np.arange(nm), counts)
    n = len(v_idx)

    p_c, v_eff = _vintage_effects(months)
    pc = p_c[v_idx]
    pa = np.where(pc > 0.3, 0.20, np.where(pc < 0.16, 0.42, 0.34))
    u = rng.random(n)
    band = np.where(u < pa, 0, np.where(u < pa + (1 - pa - pc), 1, 2))

    product = rng.choice(len(C.PRODUCTS), size=n, p=[0.50, 0.30, 0.20])
    median = np.array([8_000_000, 1_500_000, 6_000_000])[product]
    sigma = np.array([0.55, 0.50, 0.40])[product]
    principal = rng.lognormal(np.log(median), sigma)
    lo = np.array([2_000_000, 300_000, 2_000_000])[product]
    hi = np.array([30_000_000, 6_000_000, 20_000_000])[product]
    principal = np.round(np.clip(principal, lo, hi) / 50_000) * 50_000

    tenor = np.zeros(n, dtype=int)
    tenor_opts = [([3, 6, 9, 12], [0.10, 0.35, 0.20, 0.35]),
                  ([2, 3, 6], [0.30, 0.50, 0.20]),
                  ([6, 9, 12], [0.35, 0.25, 0.40])]
    for p, (opts, pr) in enumerate(tenor_opts):
        m = product == p
        tenor[m] = rng.choice(opts, size=m.sum(), p=pr)

    rate = np.array([0.015, 0.020, 0.028])[band] + rng.normal(0, 0.0015, n)
    rate = np.clip(rate, 0.01, 0.04)
    installment = np.round(principal * (1 / tenor + rate) / 1000) * 1000

    day = rng.integers(1, 29, n)
    disburse = np.array(
        [months[v].start_time + pd.Timedelta(days=int(d) - 1) for v, d in zip(v_idx, day)]
    )

    region = rng.choice(
        len(C.REGIONS), size=n, p=[0.20, 0.17, 0.12, 0.14, 0.08, 0.07, 0.05, 0.04, 0.03, 0.10]
    )
    income = rng.choice(["< 5 jt", "5-10 jt", "10-20 jt", "> 20 jt"], size=n, p=[0.30, 0.40, 0.22, 0.08])

    loans = pd.DataFrame(
        {
            "loan_id": [f"LN{i + 1:07d}" for i in range(n)],
            "customer_id": [f"CU{rng.integers(1_000_000, 9_999_999)}" for _ in range(n)],
            "disburse_date": pd.to_datetime(disburse),
            "vintage": [str(months[v]) for v in v_idx],
            "vintage_idx": v_idx,
            "product": np.array(C.PRODUCTS)[product],
            "risk_band": np.array(C.RISK_BANDS)[band],
            "band_idx": band,
            "region": np.array(C.REGIONS)[region],
            "income_band": income,
            "principal": principal,
            "tenor": tenor,
            "monthly_rate": rate.round(4),
            "installment": installment,
            "due_day": day,
        }
    )
    return loans, v_eff
