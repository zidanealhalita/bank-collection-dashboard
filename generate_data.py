"""Bangkitkan ulang data dummy ke folder data/ (format Parquet).

Pemakaian:
    python generate_data.py              # seed default
    python generate_data.py --seed 7     # seed lain
"""
from __future__ import annotations

import argparse
import time

from src import config as C
from src.gen_sim import simulate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=C.SEED)
    args = ap.parse_args()

    t0 = time.time()
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tables = simulate(args.seed)
    for name, df in tables.items():
        df.to_parquet(C.DATA_FILES[name], index=False)
        print(f"{name:12s} {len(df):>9,d} baris  -> {C.DATA_FILES[name].name}")
    print(f"Selesai dalam {time.time() - t0:.1f} detik")


if __name__ == "__main__":
    main()
