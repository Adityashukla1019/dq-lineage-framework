-- Metadata / governance tables. Data-layer tables (raw_loans, stg_loans, clean_loans,
-- quarantine_loans) are created by the pipeline and all carry a run_id column.
CREATE TABLE IF NOT EXISTS dq_runs (
    run_id TEXT PRIMARY KEY, run_ts TEXT, batch_date TEXT,
    rows_raw INTEGER, rows_clean INTEGER, rows_quarantined INTEGER, reconciled INTEGER,
    stg_dq_score REAL, clean_dq_score REAL,
    stg_defect_rate_any REAL, clean_defect_rate_any REAL,
    stg_defect_rate_critical REAL, clean_defect_rate_critical REAL,
    breaches INTEGER
);
CREATE TABLE IF NOT EXISTS dq_results (
    run_id TEXT, layer TEXT, rule_id TEXT, name TEXT, dimension TEXT, column_name TEXT,
    severity TEXT, threshold REAL, total INTEGER, failed INTEGER, pass_rate REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS lineage (
    run_id TEXT, step_no INTEGER, source TEXT, transformation TEXT, target TEXT,
    rows_in INTEGER, rows_out INTEGER, ts TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    run_id TEXT, ts TEXT, rule_id TEXT, level TEXT, pass_rate REAL, threshold REAL, message TEXT
);
