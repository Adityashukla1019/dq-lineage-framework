"""Generate messy, Lending-Club-style loan batches with *known, injected* defects.

Because we inject the defects ourselves, we can verify the DQ engine finds them
(see tests/test_engine.py). `mult` scales all defect rates, which lets us simulate
an upstream incident (e.g. mult=4) and watch the alerting fire.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

GRADE_BANDS = {"A": (5.5, 9.5), "B": (9.5, 13.5), "C": (13.5, 17.5), "D": (17.5, 21.5),
               "E": (21.5, 25.5), "F": (25.5, 28.5), "G": (28.5, 31.5)}
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
          "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
# base defect rates (fraction of rows) at mult = 1.0
BASE = dict(null_id=.002, dup_id=.004, amt_range=.004, funded_gt=.004, rate_range=.005, rate_na=.003,
            grade_invalid=.001, inc_null=.010, inc_neg=.003, dti_range=.003, bad_date=.002, future_date=.004,
            stale_date=.006, state_invalid=.005, state_lower=.010, email_bad=.010, status_bad=.003,
            grade_rate_mismatch=.012, term_bad=.001)


def generate_batch(n: int, batch_date: date, mult: float = 1.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    grades = np.array(list(GRADE_BANDS))
    grade = rng.choice(grades, n, p=[.20, .30, .25, .15, .06, .03, .01])
    lo = np.array([GRADE_BANDS[g][0] for g in grade]); hi = np.array([GRADE_BANDS[g][1] for g in grade])
    int_rate = np.round(rng.uniform(lo, hi), 2)
    loan_amnt = np.round(np.clip(rng.lognormal(9.6, 0.6, n), 1000, 40000), -2)
    funded = np.round(loan_amnt * np.where(rng.random(n) < .1, rng.uniform(.9, 1, n), 1), -1)
    term = rng.choice([36, 60], n, p=[.7, .3])
    dti = np.round(np.clip(rng.normal(18, 8, n), 0, 60), 2)
    inc = np.round(rng.lognormal(11.1, 0.55, n), 0)
    issue = np.array([batch_date - timedelta(days=int(d)) for d in rng.integers(0, 60, n)])
    default_p = {"A": .03, "B": .07, "C": .12, "D": .18, "E": .25, "F": .32, "G": .38}
    p_def = np.array([default_p[g] for g in grade])
    status = np.where(rng.random(n) < p_def, "Charged Off",
                      rng.choice(["Current", "Fully Paid", "Late"], n, p=[.6, .33, .07]))
    tag = f"{batch_date:%y%m%d}"
    df = pd.DataFrame({
        "loan_id": [f"{tag}{i:06d}" for i in range(n)],
        "member_id": rng.integers(10_000_000, 99_999_999, n).astype(str),
        "loan_amnt": loan_amnt.astype(int).astype(str),
        "funded_amnt": funded.astype(int).astype(str),
        "term": [f" {t} months" for t in term],
        "int_rate": int_rate.astype(str),
        "grade": grade,
        "annual_inc": inc.astype(int).astype(str),
        "dti": dti.astype(str),
        "issue_d": [d.isoformat() for d in issue],
        "loan_status": status,
        "purpose": rng.choice(["debt_consolidation", "credit_card", "home_improvement", "other", "car"], n),
        "addr_state": rng.choice(STATES, n),
        "email": [f"user{i}@example.com" for i in range(n)],
    })

    def hit(key):
        return rng.random(n) < min(BASE[key] * mult, 0.5)

    m = hit("null_id");            df.loc[m, "loan_id"] = ""
    m = hit("dup_id");             df.loc[m, "loan_id"] = df["loan_id"].sample(m.sum(), random_state=seed, replace=True).values
    m = hit("amt_range");          df.loc[m, "loan_amnt"] = rng.choice(["0", "-500", "900000", "150"], m.sum())
    m = hit("funded_gt");          df.loc[m, "funded_amnt"] = (pd.to_numeric(df.loc[m, "loan_amnt"], errors="coerce") * 1.2).round().astype("Int64").astype(str)
    m = hit("rate_range");         df.loc[m, "int_rate"] = rng.choice(["0.0", "-3.2", "45.9", "78.0"], m.sum())
    m = hit("rate_na");            df.loc[m, "int_rate"] = "N/A"
    m = hit("grade_invalid");      df.loc[m, "grade"] = rng.choice(["H", "Z", "?"], m.sum())
    m = hit("inc_null");           df.loc[m, "annual_inc"] = ""
    m = hit("inc_neg");            df.loc[m, "annual_inc"] = "-50000"
    m = hit("dti_range");          df.loc[m, "dti"] = rng.choice(["-5", "250", "999"], m.sum())
    m = hit("bad_date");           df.loc[m, "issue_d"] = "31/13/2026"
    m = hit("future_date");        df.loc[m, "issue_d"] = [(batch_date + timedelta(days=int(d))).isoformat() for d in rng.integers(1, 400, m.sum())]
    m = hit("stale_date");         df.loc[m, "issue_d"] = [(batch_date - timedelta(days=int(d))).isoformat() for d in rng.integers(150, 900, m.sum())]
    m = hit("state_invalid");      df.loc[m, "addr_state"] = rng.choice(["XX", "ZZ", "99"], m.sum())
    m = hit("state_lower");        df.loc[m, "addr_state"] = df.loc[m, "addr_state"].str.lower()
    m = hit("email_bad");          df.loc[m, "email"] = df.loc[m, "email"].str.replace("@", "", regex=False)
    m = hit("status_bad");         df.loc[m, "loan_status"] = "Unknown"
    m = hit("term_bad");           df.loc[m, "term"] = " 48 months"
    m = hit("grade_rate_mismatch")
    df.loc[m, "int_rate"] = [str(round(rng.uniform(*GRADE_BANDS[rng.choice([x for x in GRADE_BANDS if x != g])]), 2))
                             for g in df.loc[m, "grade"]]
    # formatting noise that staging is expected to *fix* (not DQ failures)
    m = rng.random(n) < .03;       df.loc[m, "int_rate"] = df.loc[m, "int_rate"].where(df.loc[m, "int_rate"].str.contains("N/A|-"), df.loc[m, "int_rate"] + "%")
    m = rng.random(n) < .005;      df.loc[m, "grade"] = " " + df.loc[m, "grade"] + " "
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=25_000)
    ap.add_argument("--batch-date", default="2026-09-01")
    ap.add_argument("--mult", type=float, default=1.0)
    ap.add_argument("--out", default="data/incoming/batch.csv")
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    generate_batch(a.rows, date.fromisoformat(a.batch_date), a.mult).to_csv(a.out, index=False)
    print(f"wrote {a.out}")
