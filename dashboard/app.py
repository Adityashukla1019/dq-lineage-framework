"""Data-quality & lineage dashboard.   streamlit run dashboard/app.py"""
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "dq.db"
st.set_page_config(page_title="Data Quality Monitor", layout="wide", page_icon="✅")

if not DB.exists():
    st.error("No database yet. Run `make simulate` first (see README).")
    st.stop()


@st.cache_data(ttl=30)
def q(sql, params=()):
    con = sqlite3.connect(DB)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


runs = q("SELECT * FROM dq_runs ORDER BY batch_date")
st.title("✅ Data Quality & Lineage Monitor")
st.caption("Config-driven rules (config/dq_rules.yaml) · raw → staging → clean → reporting · breach alerting")

run_id = st.sidebar.selectbox("Run", runs.run_id.tolist()[::-1])
layer = st.sidebar.radio("Layer", ["staging", "clean"], help="staging = before cleaning, clean = after")
cur = runs[runs.run_id == run_id].iloc[0]

c = st.columns(5)
c[0].metric("Rows ingested", f"{cur.rows_raw:,}")
c[1].metric("Quarantined", f"{cur.rows_quarantined:,}", f"{100 * cur.rows_quarantined / cur.rows_raw:.2f}%", delta_color="off")
c[2].metric("DQ score (staging → clean)", f"{cur.stg_dq_score:.2f} → {cur.clean_dq_score:.2f}")
c[3].metric("Records with any defect", f"{cur.stg_defect_rate_any:.2f}% → {cur.clean_defect_rate_any:.2f}%")
c[4].metric("Rule breaches", int(cur.breaches), "reconciled ✓" if cur.reconciled else "RECON FAILED", delta_color="off")

t1, t2, t3, t4, t5 = st.tabs(["📋 Scorecard", "📈 Trend", "🔁 Before vs After", "🧬 Lineage", "🚨 Alerts & Quarantine"])

with t1:
    r = q("SELECT * FROM dq_results WHERE run_id=? AND layer=?", (run_id, layer))
    a, b = st.columns([3, 2])
    fig = px.bar(r.sort_values("rule_id"), x="pass_rate", y="rule_id", orientation="h", color="status",
                 color_discrete_map={"PASS": "#16a34a", "BREACH": "#dc2626"}, hover_data=["name", "failed", "threshold"],
                 title=f"Pass rate by rule - {layer}")
    fig.update_xaxes(range=[min(90, r.pass_rate.min() - 1), 100.2]); fig.update_yaxes(autorange="reversed")
    a.plotly_chart(fig, width="stretch")
    dim = r.groupby("dimension").agg(rules=("rule_id", "count"), avg_pass_rate=("pass_rate", "mean"), breaches=("status", lambda s: (s == "BREACH").sum())).round(2).reset_index()
    b.subheader("By dimension"); b.dataframe(dim, hide_index=True, width="stretch")
    st.dataframe(r[["rule_id", "name", "dimension", "severity", "threshold", "failed", "total", "pass_rate", "status"]],
                 hide_index=True, width="stretch")

with t2:
    tr = q("SELECT * FROM rpt_dq_trend")
    st.plotly_chart(px.line(tr, x="batch_date", y=["stg_dq_score", "clean_dq_score"], markers=True, title="Overall DQ score per run"), width="stretch")
    allr = q("SELECT d.*, r.batch_date FROM dq_results d JOIN dq_runs r USING(run_id) WHERE layer='staging'")
    pick = st.multiselect("Rules to trend", sorted(allr.rule_id.unique()), default=["R002", "R006", "R014", "R018"])
    st.plotly_chart(px.line(allr[allr.rule_id.isin(pick)], x="batch_date", y="pass_rate", color="rule_id", markers=True, title="Rule pass rate over time (staging)"), width="stretch")
    st.plotly_chart(px.bar(tr, x="batch_date", y="quarantine_pct", title="% rows quarantined per run"), width="stretch")

with t3:
    long = runs.melt(id_vars="batch_date", value_vars=["stg_defect_rate_any", "clean_defect_rate_any"], var_name="layer", value_name="defect_%")
    st.plotly_chart(px.bar(long, x="batch_date", y="defect_%", color="layer", barmode="group", title="% of records failing ≥1 rule: staging vs clean"), width="stretch")
    both = q("SELECT rule_id, name, layer, failed FROM dq_results WHERE run_id=?", (run_id,)).pivot_table(index=["rule_id", "name"], columns="layer", values="failed").reset_index()
    st.subheader(f"Failed rows per rule - {run_id}"); st.dataframe(both, hide_index=True, width="stretch")
    st.caption("Rules marked critical are removed by quarantine; warning rules can remain after cleaning unless standardisation fixes them (e.g. lower-case state codes).")

with t4:
    lin = q("SELECT step_no, source, transformation, target, rows_in, rows_out FROM lineage WHERE run_id=? ORDER BY step_no", (run_id,))
    st.dataframe(lin, hide_index=True, width="stretch")
    dot = "digraph { rankdir=LR; node [shape=box, style=rounded]; " + " ".join(
        f'"{r.source.split("/")[-1]}" -> "{r.target}" [label="{r.rows_in:,}→{r.rows_out:,}"];' for r in lin.itertuples()) + "}"
    st.graphviz_chart(dot)

with t5:
    al = q("SELECT ts, rule_id, level, pass_rate, threshold, message FROM alerts WHERE run_id=?", (run_id,))
    st.subheader(f"Alerts for {run_id}: {len(al)}")
    st.dataframe(al, hide_index=True, width="stretch") if len(al) else st.success("No breaches in this run.")
    qr = q("SELECT failed_rules FROM quarantine_loans WHERE run_id=?", (run_id,))
    if len(qr):
        counts = qr.failed_rules.str.split(",").explode().value_counts().rename_axis("rule_id").reset_index(name="rows")
        st.plotly_chart(px.bar(counts, x="rule_id", y="rows", title="Quarantined rows by failing rule (a row can fail several)"), width="stretch")
        st.subheader("Sample of quarantined records")
        st.dataframe(q("SELECT loan_id, loan_amnt, funded_amnt, int_rate, grade, issue_d, addr_state, failed_rules FROM quarantine_loans WHERE run_id=? LIMIT 200", (run_id,)), hide_index=True, width="stretch")
