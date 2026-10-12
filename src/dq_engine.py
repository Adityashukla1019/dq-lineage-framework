"""Config-driven data-quality rule engine.

Design notes
------------
* Every check returns a boolean *failure mask* (True = row violates the rule).
  Masks (not just counts) let the pipeline quarantine the exact failing rows
  and explain *why* each row was rejected.
* Null handling: only `not_null` penalises nulls. Every other rule ignores
  nulls so one bad value is not double-counted across rules.
* Pass rate = 100 * (1 - failed / total rows).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

CHECKS: dict[str, Callable] = {}


def check(name: str):
    def deco(fn):
        CHECKS[name] = fn
        return fn
    return deco


# --------------------------------------------------------------------------- checks
@check("not_null")
def _not_null(df, col, p, ctx):
    return df[col].isna()


@check("unique")
def _unique(df, col, p, ctx):
    return df[col].notna() & df[col].duplicated(keep="first")


@check("range")
def _range(df, col, p, ctx):
    v = pd.to_numeric(df[col], errors="coerce")
    low = (v <= p["min"]) if p.get("exclusive_min") else (v < p["min"])
    return v.notna() & (low | (v > p["max"]))


@check("allowed_values")
def _allowed(df, col, p, ctx):
    return df[col].notna() & ~df[col].isin(p["values"])


@check("regex")
def _regex(df, col, p, ctx):
    s = df[col].astype("string")
    return s.notna() & ~s.str.match(p["pattern"]).fillna(False).astype(bool)


@check("not_future_date")
def _not_future(df, col, p, ctx):
    d = pd.to_datetime(df[col], errors="coerce")
    return d.notna() & (d > pd.Timestamp(ctx["batch_date"]))


@check("max_age_days")
def _max_age(df, col, p, ctx):
    d = pd.to_datetime(df[col], errors="coerce")
    age = (pd.Timestamp(ctx["batch_date"]) - d).dt.days
    return d.notna() & (age > p["days"])


@check("cross_field")
def _cross(df, col, p, ctx):
    req = p.get("requires", [])
    evaluable = df[req].notna().all(axis=1) if req else pd.Series(True, index=df.index)
    valid = df.eval(p["expr"])
    return evaluable & ~valid.fillna(False).astype(bool)


@check("lookup_range")
def _lookup(df, col, p, ctx):
    bands = p["bands"]
    g = df[p["group_by"]]
    lo = g.map({k: v[0] for k, v in bands.items()})
    hi = g.map({k: v[1] for k, v in bands.items()})
    v = pd.to_numeric(df[col], errors="coerce")
    return v.notna() & lo.notna() & ((v < lo) | (v > hi))


# --------------------------------------------------------------------------- engine
@dataclass
class RuleResult:
    rule_id: str
    name: str
    dimension: str
    column: str
    severity: str
    threshold: float
    total: int
    failed: int
    pass_rate: float
    status: str  # PASS | BREACH

    def to_dict(self):
        return asdict(self)


def load_rules(path: str | Path) -> list[dict]:
    rules = yaml.safe_load(Path(path).read_text())["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids in config"
    for r in rules:
        if r["type"] not in CHECKS:
            raise ValueError(f"{r['id']}: unknown rule type '{r['type']}'")
    return rules


def run_rules(df: pd.DataFrame, rules: list[dict], batch_date: date, layer: str = "staging"):
    """Return (results, fail_matrix). fail_matrix has one boolean column per rule id."""
    ctx = {"batch_date": batch_date}
    results, masks = [], {}
    n = len(df)
    for r in rules:
        if layer not in r.get("layers", ["staging", "clean"]):
            continue
        mask = CHECKS[r["type"]](df, r["column"], r.get("params", {}), ctx).fillna(False).astype(bool)
        masks[r["id"]] = mask
        failed = int(mask.sum())
        pass_rate = round(100.0 * (1 - failed / n), 4) if n else 100.0
        results.append(RuleResult(r["id"], r["name"], r["dimension"], r["column"], r["severity"],
                                  float(r["threshold"]), n, failed, pass_rate,
                                  "PASS" if pass_rate >= r["threshold"] else "BREACH"))
    return results, pd.DataFrame(masks, index=df.index)


def summarise(results: list[RuleResult], fail_matrix: pd.DataFrame, rules: list[dict]) -> dict:
    """Roll rule results up into layer-level scores."""
    sev = {r["id"]: r["severity"] for r in rules}
    crit_cols = [c for c in fail_matrix.columns if sev[c] == "critical"]
    n = len(fail_matrix)
    return {
        "rows": n,
        "dq_score": round(sum(r.pass_rate for r in results) / len(results), 4) if results else 100.0,
        "defect_rate_any": round(100 * fail_matrix.any(axis=1).mean(), 4) if n else 0.0,
        "defect_rate_critical": round(100 * fail_matrix[crit_cols].any(axis=1).mean(), 4) if n and crit_cols else 0.0,
        "breaches": sum(r.status == "BREACH" for r in results),
    }
