"""Export static charts for the README from the DQ database."""
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "dq.db")
runs = pd.read_sql("SELECT * FROM dq_runs ORDER BY batch_date", con)
(ROOT / "docs").mkdir(exist_ok=True)

fig, ax = plt.subplots(1, 2, figsize=(11, 4))
x = runs.batch_date.str[5:]
ax[0].plot(x, runs.stg_dq_score, "o-", label="staging (before)"); ax[0].plot(x, runs.clean_dq_score, "s-", label="clean (after)")
for i, b in enumerate(runs.breaches):
    if b: ax[0].annotate(f"{b} breaches", (x[i], runs.stg_dq_score[i]), textcoords="offset points", xytext=(38, 6), ha="left", color="crimson")
ax[0].set_title("Overall DQ score per run"); ax[0].set_ylabel("avg rule pass rate (%)"); ax[0].legend()
w = 0.38; idx = range(len(runs))
ax[1].bar([i - w / 2 for i in idx], runs.stg_defect_rate_any, w, label="staging")
ax[1].bar([i + w / 2 for i in idx], runs.clean_defect_rate_any, w, label="clean")
ax[1].set_xticks(list(idx)); ax[1].set_xticklabels(x); ax[1].set_title("% records failing ≥1 rule"); ax[1].legend()
fig.tight_layout(); fig.savefig(ROOT / "docs" / "dq_trend.png", dpi=140)
print("saved docs/dq_trend.png")
