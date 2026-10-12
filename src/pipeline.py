"""raw -> staging -> (DQ) -> quarantine / clean -> reporting, with lineage + alerts.

    python -m src.pipeline --csv data/incoming/batch.csv --batch-date 2026-09-01

Layers (all persisted to SQLite, every row tagged with run_id):
  raw_loans         exact copy of the source file (all text) - never modified
  stg_loans         typed + trimmed; DQ rules run here ("before")
  quarantine_loans  rows failing a CRITICAL rule, with the list of failed rule ids
  clean_loans       standardised, PII-masked, passed critical rules; DQ rules re-run ("after")
  rpt_* views       reporting layer built only on clean_loans (sql/reporting.sql)
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src import alerts as alerting
from src.dq_engine import load_rules, run_rules, summarise

ROOT = Path(__file__).resolve().parents[1]
DATA_TABLES = ["raw_loans", "stg_loans", "clean_loans", "quarantine_loans"]
META_TABLES = ["dq_results", "lineage", "alerts"]
NUMERIC = ["loan_amnt", "funded_amnt", "int_rate", "annual_inc", "dti"]


class Lineage:
    def __init__(self, run_id):
        self.run_id, self.rows = run_id, []

    def add(self, source, transformation, target, rows_in, rows_out):
        self.rows.append({"run_id": self.run_id, "step_no": len(self.rows) + 1, "source": source,
                          "transformation": transformation, "target": target, "rows_in": int(rows_in),
                          "rows_out": int(rows_out), "ts": datetime.now().isoformat(timespec="seconds")})

    def frame(self):
        return pd.DataFrame(self.rows)


# ------------------------------------------------------------------ transformations
def stage(raw: pd.DataFrame) -> pd.DataFrame:
    """Type-cast and trim. Does NOT fix business-rule violations - those are for DQ to find."""
    df = raw.copy()
    for c in df.columns:
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c].str.replace(r"[%$,]", "", regex=True), errors="coerce")
    df["term"] = pd.to_numeric(df["term"].str.extract(r"(\d+)")[0], errors="coerce")
    df["issue_d"] = pd.to_datetime(df["issue_d"], format="mixed", errors="coerce")
    return df


def mask_email(s: pd.Series) -> pd.Series:
    return s.map(lambda e: hashlib.sha256(str(e).lower().encode()).hexdigest()[:16] if pd.notna(e) else pd.NA)


def split_and_clean(stg: pd.DataFrame, fail: pd.DataFrame, rules: list[dict]):
    crit = [r["id"] for r in rules if r["severity"] == "critical" and r["id"] in fail.columns]
    bad = fail[crit].any(axis=1)
    quarantine = stg[bad].copy()
    quarantine["failed_rules"] = fail.loc[bad, crit].apply(lambda r: ",".join(c for c in crit if r[c]), axis=1)

    clean = stg[~bad].copy()
    clean["addr_state"] = clean["addr_state"].str.upper()          # standardise (auto-remediation)
    clean["grade"] = clean["grade"].str.upper()
    clean["email_hash"] = mask_email(clean["email"])                # privacy: no raw PII downstream
    clean = clean.drop(columns=["email"])
    clean["is_default"] = clean["loan_status"].isin(["Charged Off", "Default"]).astype(int)
    return clean, quarantine


# ------------------------------------------------------------------ persistence
def _purge(con, run_id):
    for t in DATA_TABLES + META_TABLES + ["dq_runs"]:
        try:
            con.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))
        except sqlite3.OperationalError:
            pass


def _write(con, df, table, run_id):
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype).startswith("datetime"):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.insert(0, "run_id", run_id)
    out.astype(object).where(out.notna(), None).to_sql(table, con, if_exists="append", index=False)


def _results_frame(results, run_id, layer):
    d = pd.DataFrame([r.to_dict() for r in results]).rename(columns={"column": "column_name"})
    d.insert(0, "layer", layer); d.insert(0, "run_id", run_id)
    return d


# ------------------------------------------------------------------ orchestration
def run(csv: str | Path, batch_date: date, db: str | Path = ROOT / "data" / "dq.db",
        rules_path: str | Path = ROOT / "config" / "dq_rules.yaml", run_id: str | None = None,
        verbose: bool = True) -> dict:
    run_id = run_id or f"run_{batch_date.isoformat()}"
    rules = load_rules(rules_path)
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript((ROOT / "sql" / "schema.sql").read_text())
    _purge(con, run_id)                                   # idempotent re-runs
    lin = Lineage(run_id)

    # 1. ingest
    raw = pd.read_csv(csv, dtype=str, keep_default_na=False)
    _write(con, raw, "raw_loans", run_id)
    lin.add(str(csv), "ingest as-is (all columns TEXT)", "raw_loans", len(raw), len(raw))

    # 2. stage
    stg = stage(raw)
    _write(con, stg, "stg_loans", run_id)
    lin.add("raw_loans", "trim, blank->NULL, cast numerics/dates, strip %/$ symbols", "stg_loans", len(raw), len(stg))

    # 3. DQ on staging ("before")
    res_stg, fail_stg = run_rules(stg, rules, batch_date, "staging")
    sum_stg = summarise(res_stg, fail_stg, rules)
    lin.add("stg_loans", f"DQ: {len(res_stg)} rules", "dq_results", len(stg), len(res_stg))

    # 4. quarantine + clean
    clean, quar = split_and_clean(stg, fail_stg, rules)
    _write(con, quar, "quarantine_loans", run_id)
    lin.add("stg_loans", "route rows failing CRITICAL rules", "quarantine_loans", len(stg), len(quar))
    _write(con, clean, "clean_loans", run_id)
    lin.add("stg_loans", "drop quarantined; upper-case state/grade; SHA-256 mask email; derive is_default",
            "clean_loans", len(stg), len(clean))

    # 5. DQ on clean ("after")
    res_cln, fail_cln = run_rules(clean, rules, batch_date, "clean")
    sum_cln = summarise(res_cln, fail_cln, rules)
    lin.add("clean_loans", f"DQ re-check: {len(res_cln)} rules", "dq_results", len(clean), len(res_cln))

    # 6. reporting views
    con.executescript((ROOT / "sql" / "reporting.sql").read_text())
    lin.add("clean_loans", "build reporting views (grade summary, monthly origination, DQ trend)", "rpt_* views", len(clean), len(clean))

    # 7. control: reconciliation  raw == clean + quarantined
    reconciled = int(len(raw) == len(clean) + len(quar))

    # 8. alerts on source quality (staging) + control failures
    alert_list = alerting.build_alerts(run_id, res_stg)
    if not reconciled:
        alert_list.append({"run_id": run_id, "ts": datetime.now().isoformat(timespec="seconds"), "rule_id": "CTRL-REC",
                           "level": "CRITICAL", "pass_rate": 0.0, "threshold": 100.0,
                           "message": f"[CRITICAL] reconciliation failed: raw={len(raw)} clean={len(clean)} quarantined={len(quar)}"})
    alerting.send(alert_list, run_id)

    # 9. persist metadata
    pd.concat([_results_frame(res_stg, run_id, "staging"), _results_frame(res_cln, run_id, "clean")]) \
        .to_sql("dq_results", con, if_exists="append", index=False)
    lin.frame().to_sql("lineage", con, if_exists="append", index=False)
    if alert_list:
        pd.DataFrame(alert_list).to_sql("alerts", con, if_exists="append", index=False)
    summary = {
        "run_id": run_id, "run_ts": datetime.now().isoformat(timespec="seconds"), "batch_date": batch_date.isoformat(),
        "rows_raw": len(raw), "rows_clean": len(clean), "rows_quarantined": len(quar), "reconciled": reconciled,
        "stg_dq_score": sum_stg["dq_score"], "clean_dq_score": sum_cln["dq_score"],
        "stg_defect_rate_any": sum_stg["defect_rate_any"], "clean_defect_rate_any": sum_cln["defect_rate_any"],
        "stg_defect_rate_critical": sum_stg["defect_rate_critical"], "clean_defect_rate_critical": sum_cln["defect_rate_critical"],
        "breaches": sum_stg["breaches"],
    }
    pd.DataFrame([summary]).to_sql("dq_runs", con, if_exists="append", index=False)
    con.commit(); con.close()
    if verbose:
        print(f"{run_id}: raw={len(raw):,} clean={len(clean):,} quarantined={len(quar):,} reconciled={bool(reconciled)} | "
              f"DQ score {sum_stg['dq_score']:.2f} -> {sum_cln['dq_score']:.2f} | defects(any) {sum_stg['defect_rate_any']:.2f}% -> "
              f"{sum_cln['defect_rate_any']:.2f}% | breaches={sum_stg['breaches']}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--batch-date", required=True, help="YYYY-MM-DD (reference date for timeliness rules)")
    ap.add_argument("--db", default=str(ROOT / "data" / "dq.db"))
    ap.add_argument("--rules", default=str(ROOT / "config" / "dq_rules.yaml"))
    a = ap.parse_args()
    run(a.csv, date.fromisoformat(a.batch_date), a.db, a.rules)
