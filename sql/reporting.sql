-- Reporting layer: views over the CLEAN layer only (quarantined rows never appear here).
DROP VIEW IF EXISTS rpt_loan_summary_by_grade;
CREATE VIEW rpt_loan_summary_by_grade AS
SELECT grade,
       COUNT(*)                                   AS loans,
       ROUND(AVG(int_rate), 2)                    AS avg_int_rate,
       ROUND(SUM(funded_amnt), 0)                 AS total_funded,
       ROUND(100.0 * AVG(is_default), 2)          AS default_rate_pct
FROM clean_loans GROUP BY grade ORDER BY grade;

DROP VIEW IF EXISTS rpt_monthly_origination;
CREATE VIEW rpt_monthly_origination AS
SELECT substr(issue_d, 1, 7) AS month, COUNT(*) AS loans, ROUND(SUM(funded_amnt), 0) AS funded
FROM clean_loans GROUP BY month ORDER BY month;

DROP VIEW IF EXISTS rpt_dq_trend;
CREATE VIEW rpt_dq_trend AS
SELECT r.run_id, r.batch_date, r.rows_raw, r.rows_quarantined,
       ROUND(100.0 * r.rows_quarantined / r.rows_raw, 2) AS quarantine_pct,
       r.stg_dq_score, r.clean_dq_score, r.stg_defect_rate_any, r.clean_defect_rate_any, r.breaches
FROM dq_runs r ORDER BY r.batch_date;
