"""Apache Airflow DAG: run the DQ pipeline daily.

Provided for orchestration; not exercised by this repo's CI (CI uses the GitHub Actions
schedule in .github/workflows/scheduled_run.yml). To use: `pip install apache-airflow`, point
`dags_folder` at this directory, and set the PROJECT_ROOT env var.
"""
import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


def _ingest_and_check(ds, **_):
    from datetime import date
    from pathlib import Path
    from src.pipeline import run
    csv = Path(PROJECT_ROOT) / "data" / "incoming" / f"loans_{ds}.csv"
    if not csv.exists():
        raise FileNotFoundError(f"expected source file not delivered: {csv}")   # timeliness control
    summary = run(csv, date.fromisoformat(ds), Path(PROJECT_ROOT) / "data" / "dq.db")
    if not summary["reconciled"]:
        raise ValueError("reconciliation control failed")


with DAG(
    dag_id="loan_dq_pipeline",
    start_date=datetime(2026, 9, 1),
    schedule="0 6 * * *",
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["data-quality"],
) as dag:
    PythonOperator(task_id="ingest_validate_clean_report", python_callable=_ingest_and_check)
