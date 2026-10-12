"""Simulate N daily batches (one with an upstream incident) and run the pipeline on each.

    python -m src.simulate --batches 6 --rows 25000
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from src.generate_loans import generate_batch
from src.pipeline import ROOT, run

DEFAULT_MULTS = [1.0, 1.0, 0.8, 1.1, 4.0, 1.0]   # batch 5 simulates an upstream incident


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=6)
    ap.add_argument("--rows", type=int, default=25_000)
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--db", default=str(ROOT / "data" / "dq.db"))
    ap.add_argument("--keep-db", action="store_true", help="append to existing DB instead of resetting")
    a = ap.parse_args()

    db = Path(a.db)
    if db.exists() and not a.keep_db:
        db.unlink()
    inc = ROOT / "data" / "incoming"; inc.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(a.start)
    for i in range(a.batches):
        d = start + timedelta(days=i)
        mult = DEFAULT_MULTS[i % len(DEFAULT_MULTS)]
        csv = inc / f"loans_{d.isoformat()}.csv"
        generate_batch(a.rows, d, mult, seed=100 + i).to_csv(csv, index=False)
        print(f"[batch {i + 1}] defect multiplier x{mult}")
        run(csv, d, db)


if __name__ == "__main__":
    main()
