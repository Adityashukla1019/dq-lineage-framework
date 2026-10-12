import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import alerts
from src.adapt_lendingclub import adapt
from src.generate_loans import generate_batch
from src.pipeline import mask_email, run, stage

BD = date(2026, 9, 1)


def make(tmp_path, mult, rows=10_000, seed=7):
    csv = tmp_path / f"b_{mult}.csv"
    generate_batch(rows, BD, mult, seed).to_csv(csv, index=False)
    return csv


def q(db, sql):
    con = sqlite3.connect(db)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


def test_stage_casts_and_cleans_types():
    raw = pd.DataFrame({"loan_id": ["1"], "member_id": ["9"], "loan_amnt": ["$1,000"], "funded_amnt": ["1000"],
                        "term": [" 36 months"], "int_rate": ["13.5%"], "grade": [" B "], "annual_inc": [""],
                        "dti": ["N/A"], "issue_d": ["31/13/2026"], "loan_status": ["Current"], "purpose": ["car"],
                        "addr_state": ["ca"], "email": ["a@b.com"]})
    s = stage(raw)
    assert s.loc[0, "loan_amnt"] == 1000 and s.loc[0, "int_rate"] == 13.5 and s.loc[0, "term"] == 36
    assert s.loc[0, "grade"] == "B" and pd.isna(s.loc[0, "annual_inc"]) and pd.isna(s.loc[0, "dti"]) and pd.isna(s.loc[0, "issue_d"])


def test_email_mask_is_deterministic_and_irreversible_looking():
    h = mask_email(pd.Series(["A@x.com", "a@x.com"]))
    assert h.iloc[0] == h.iloc[1] and "@" not in h.iloc[0] and len(h.iloc[0]) == 16


@pytest.fixture(scope="module")
def healthy(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("h"); db = tmp / "dq.db"
    return db, run(make(tmp, 1.0), BD, db, verbose=False)


def test_reconciliation_control_and_row_counts(healthy):
    db, s = healthy
    assert s["reconciled"] == 1 and s["rows_raw"] == s["rows_clean"] + s["rows_quarantined"] == 10_000


def test_no_critical_defects_reach_clean_layer(healthy):
    _, s = healthy
    assert s["clean_defect_rate_critical"] == 0.0 and s["stg_defect_rate_critical"] > 0


def test_clean_layer_has_no_raw_pii_and_has_hash(healthy):
    db, _ = healthy
    cols = q(db, "SELECT * FROM clean_loans LIMIT 1").columns
    assert "email" not in cols and "email_hash" in cols


def test_every_quarantined_row_has_a_reason(healthy):
    db, s = healthy
    qd = q(db, "SELECT failed_rules FROM quarantine_loans")
    assert len(qd) == s["rows_quarantined"] and qd.failed_rules.str.len().gt(0).all()


def test_lineage_is_complete_and_ordered(healthy):
    db, _ = healthy
    lin = q(db, "SELECT * FROM lineage ORDER BY step_no")
    assert lin.target.tolist()[:4] == ["raw_loans", "stg_loans", "dq_results", "quarantine_loans"]
    assert lin.rows_in.iloc[0] == 10_000


def test_healthy_batch_has_no_breaches(healthy):
    assert healthy[1]["breaches"] == 0


def test_incident_batch_breaches_and_alerts(tmp_path):
    db = tmp_path / "dq.db"
    s = run(make(tmp_path, 4.0), BD, db, verbose=False)
    assert s["breaches"] >= 8
    a = q(db, "SELECT * FROM alerts")
    assert len(a) == s["breaches"] and set(a.level) <= {"CRITICAL", "WARNING"}


def test_rerun_same_run_id_is_idempotent(tmp_path):
    db = tmp_path / "dq.db"; csv = make(tmp_path, 1.0, rows=3000)
    run(csv, BD, db, verbose=False); run(csv, BD, db, verbose=False)
    assert q(db, "SELECT COUNT(*) n FROM dq_runs").n[0] == 1
    assert q(db, "SELECT COUNT(*) n FROM raw_loans").n[0] == 3000


def test_reporting_views_use_clean_data_only(healthy):
    db, s = healthy
    assert q(db, "SELECT SUM(loans) n FROM rpt_loan_summary_by_grade").n[0] == s["rows_clean"]


def test_email_alert_only_sent_when_configured(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send_message(self, m): sent.append(m)
        def starttls(self): pass
        def login(self, *a): pass

    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    al = [{"level": "CRITICAL", "message": "x"}]
    for k in ("SMTP_HOST", "ALERT_FROM", "ALERT_TO"):
        monkeypatch.delenv(k, raising=False)
    alerts.send(al, "r1"); assert sent == []
    monkeypatch.setenv("SMTP_HOST", "h"); monkeypatch.setenv("ALERT_FROM", "a@b.c"); monkeypatch.setenv("ALERT_TO", "d@e.f")
    alerts.send(al, "r1"); assert len(sent) == 1


def test_lendingclub_adapter_maps_columns():
    out = adapt(pd.DataFrame({"id": [1], "loan_amnt": [1000], "int_rate": [None], "extra": ["z"]}))
    assert out.loan_id[0] == "1" and out.int_rate[0] == "" and "extra" not in out.columns and "email" in out.columns
