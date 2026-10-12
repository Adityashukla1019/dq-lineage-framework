# Metric Definitions

| Metric | Definition |
|---|---|
| **Rule pass rate** | 100 × (1 − rows failing the rule ÷ total rows in the layer). Nulls only fail `not_null` rules, so one bad value is not counted against several rules. |
| **Breach** | Rule pass rate < the rule's `threshold` in config/dq_rules.yaml. |
| **DQ score** | Unweighted mean of rule pass rates in a layer. Easy to read, but it can hide a single bad rule, so always look at breaches too. |
| **Defect rate (any)** | % of records failing at least one rule (any severity). |
| **Critical defect rate** | % of records failing at least one *critical* rule. By design this is 0% in clean_loans. |
| **Quarantine %** | Rows routed to quarantine_loans ÷ raw rows. |
| **Reconciled** | raw rows = clean rows + quarantined rows. A failed reconciliation raises a CRITICAL alert. |

## DQ dimensions used
Completeness (not_null) · Uniqueness (unique) · Validity (range, allowed_values, regex) · Consistency (cross_field, lookup_range) · Timeliness (not_future_date, max_age_days)

## Severity policy
- **critical**: failing rows cannot be relied on (no key, impossible amount, funded > requested). Quarantined; never reach reporting.
- **warning**: usable but suspect (missing income, odd state code). Kept, reported, alerted when below threshold.
