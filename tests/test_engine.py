import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dq_engine import CHECKS, load_rules, run_rules, summarise

BD = date(2026, 9, 1)
CTX = {"batch_date": BD}


def mask(rule_type, series_or_df, col="x", **params):
    df = series_or_df if isinstance(series_or_df, pd.DataFrame) else pd.DataFrame({col: series_or_df})
    return CHECKS[rule_type](df, col, params, CTX).tolist()


def test_not_null():
    assert mask("not_null", pd.Series([1, None, 3])) == [False, True, False]


def test_unique_flags_only_repeat_occurrences():
    assert mask("unique", pd.Series(["a", "b", "a", "a", None, None])) == [False, False, True, True, False, False]


def test_range_inclusive_and_exclusive_min_and_null_ignored():
    s = pd.Series([0, 5, 40, 41, None])
    assert mask("range", s, min=0, max=40) == [False, False, False, True, False]
    assert mask("range", s, min=0, max=40, exclusive_min=True) == [True, False, False, True, False]


def test_allowed_values_and_regex():
    assert mask("allowed_values", pd.Series(["A", "Z", None]), values=["A", "B"]) == [False, True, False]
    assert mask("regex", pd.Series(["a@b.com", "ab.com", None], dtype="string"), pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$") == [False, True, False]


def test_date_rules():
    d = pd.Series(pd.to_datetime(["2026-08-30", "2026-09-02", "2026-01-01", None]))
    assert mask("not_future_date", d) == [False, True, False, False]
    assert mask("max_age_days", d, days=120) == [False, False, True, False]


def test_cross_field_skips_rows_with_nulls():
    df = pd.DataFrame({"funded_amnt": [100, 200, None], "loan_amnt": [100, 150, 50]})
    assert mask("cross_field", df, "funded_amnt", expr="funded_amnt <= loan_amnt", requires=["funded_amnt", "loan_amnt"]) == [False, True, False]


def test_lookup_range_grade_band():
    df = pd.DataFrame({"grade": ["A", "A", "Z", "B"], "int_rate": [7, 20, 99, None]})
    assert mask("lookup_range", df, "int_rate", group_by="grade", bands={"A": [5, 10], "B": [9, 14]}) == [False, True, False, False]


def test_unknown_rule_type_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("rules:\n  - {id: X1, name: n, dimension: d, column: c, type: nope, severity: critical, threshold: 99}\n")
    with pytest.raises(ValueError):
        load_rules(p)


def test_pass_rate_status_and_layer_filter():
    rules = [dict(id="A", name="n", dimension="Completeness", column="x", type="not_null", severity="critical", threshold=90),
             dict(id="B", name="m", dimension="Completeness", column="x", type="not_null", severity="warning", threshold=99, layers=["staging"])]
    df = pd.DataFrame({"x": [1] * 94 + [None] * 6})
    res, fm = run_rules(df, rules, BD, "staging")
    assert [r.pass_rate for r in res] == [94.0, 94.0]
    assert [r.status for r in res] == ["PASS", "BREACH"]
    assert [r.rule_id for r in run_rules(df, rules, BD, "clean")[0]] == ["A"]   # layer filter
    s = summarise(res, fm, rules)
    assert s["defect_rate_any"] == 6.0 and s["breaches"] == 1


def test_shipped_rule_catalogue_loads():
    rules = load_rules(Path(__file__).resolve().parents[1] / "config" / "dq_rules.yaml")
    assert len(rules) >= 15
    assert {r["dimension"] for r in rules} >= {"Completeness", "Uniqueness", "Validity", "Consistency", "Timeliness"}
