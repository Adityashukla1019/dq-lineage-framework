# Data Dictionary

## Source schema (raw_loans: all TEXT, exactly as received)
| Column | Description | Example | Notes |
|---|---|---|---|
| loan_id | Unique loan identifier | 260901000042 | Business key; must be present and unique |
| member_id | Borrower id | 62148231 | |
| loan_amnt | Amount requested (USD) | 20800 | Valid range 500-40,000 |
| funded_amnt | Amount funded (USD) | 20380 | Must be ≤ loan_amnt |
| term | Loan term | " 36 months" | Cast to integer months (36/60) |
| int_rate | Annual interest rate (%) | 13.5 or "13.5%" | Valid range (0, 40]; must sit in grade band |
| grade | Credit grade | B | A-G |
| annual_inc | Borrower annual income (USD) | 72927 | Non-negative; may be missing |
| dti | Debt-to-income ratio (%) | 19.61 | 0-100 |
| issue_d | Loan issue date | 2026-08-22 | Not in future; within 120 days of batch (timeliness) |
| loan_status | Current status | Charged Off | Controlled vocabulary |
| purpose | Loan purpose | car | |
| addr_state | US state code | CA | 50 states + DC |
| email | Borrower e-mail (**PII**) | user1@example.com | Hashed in clean layer |

## Layers
| Table | Purpose | Modified? |
|---|---|---|
| raw_loans | Exact copy of the source file | Never |
| stg_loans | Typed + trimmed; DQ "before" | Types only |
| quarantine_loans | Rows failing a **critical** rule + `failed_rules` | Append only |
| clean_loans | Standardised, PII-masked; DQ "after" | Derived |
| rpt_* (views) | Reporting layer, built on clean_loans only | Views |

Derived columns in clean_loans: `email_hash` (first 16 hex chars of SHA-256 of lower-cased email), `is_default` (1 if loan_status is Charged Off or Default).

## Metadata tables
| Table | Grain | Key columns |
|---|---|---|
| dq_runs | one row per pipeline run | run_id, rows_*, DQ scores, defect rates, breaches, reconciled |
| dq_results | run × layer × rule | pass_rate, failed, threshold, status |
| lineage | run × step | source, transformation, target, rows_in, rows_out |
| alerts | one row per breach | level, message |
