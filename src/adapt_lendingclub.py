"""Convert the real Lending Club 'accepted loans' CSV (Kaggle: wordsforthewise/lending-club)
into this framework's input schema.

    python -m src.adapt_lendingclub --src accepted_2007_to_2018Q4.csv --out data/incoming/lc.csv --rows 200000
    python -m src.pipeline --csv data/incoming/lc.csv --batch-date 2018-12-31

Notes: the real file has no e-mail column (left blank, rule R015 ignores nulls), and its
issue dates are historical, so raise the `days` parameter of rule R013 (timeliness) in
config/dq_rules.yaml or expect that rule to breach - which is itself a valid finding.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

RENAME = {"id": "loan_id"}
KEEP = ["loan_id", "member_id", "loan_amnt", "funded_amnt", "term", "int_rate", "grade", "annual_inc", "dti",
        "issue_d", "loan_status", "purpose", "addr_state", "email"]


def adapt(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=RENAME)
    for c in KEEP:
        if c not in df.columns:
            df[c] = ""
    return df[KEEP].fillna("").astype(str)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="data/incoming/lc.csv")
    ap.add_argument("--rows", type=int, default=None)
    a = ap.parse_args()
    raw = pd.read_csv(a.src, nrows=a.rows, low_memory=False)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    adapt(raw).to_csv(a.out, index=False)
    print(f"wrote {a.out}")
