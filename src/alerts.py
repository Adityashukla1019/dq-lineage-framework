"""Breach alerting: console + logs/alerts.log + `alerts` table, plus optional e-mail.

E-mail is only attempted when SMTP_HOST, ALERT_FROM and ALERT_TO env vars are set,
so the project runs anywhere with zero configuration.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("dq.alerts")


def _logger():
    if not log.handlers:
        (ROOT / "logs").mkdir(exist_ok=True)
        fh = logging.FileHandler(ROOT / "logs" / "alerts.log")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        log.setLevel(logging.INFO)
    return log


def build_alerts(run_id: str, results) -> list[dict]:
    alerts = []
    for r in results:
        if r.status == "BREACH":
            lvl = "CRITICAL" if r.severity == "critical" else "WARNING"
            alerts.append({
                "run_id": run_id, "ts": datetime.now().isoformat(timespec="seconds"),
                "rule_id": r.rule_id, "level": lvl, "pass_rate": r.pass_rate, "threshold": r.threshold,
                "message": f"[{lvl}] {r.rule_id} '{r.name}' ({r.dimension}): pass rate {r.pass_rate:.2f}% "
                           f"< threshold {r.threshold:.2f}% ({r.failed:,} of {r.total:,} rows failed)",
            })
    return alerts


def send(alerts: list[dict], run_id: str) -> None:
    lg = _logger()
    for a in alerts:
        lg.warning(a["message"]) if a["level"] == "WARNING" else lg.error(a["message"])
    if alerts and all(os.getenv(k) for k in ("SMTP_HOST", "ALERT_FROM", "ALERT_TO")):
        msg = EmailMessage()
        msg["Subject"] = f"[DQ] {len(alerts)} rule breach(es) in run {run_id}"
        msg["From"], msg["To"] = os.environ["ALERT_FROM"], os.environ["ALERT_TO"]
        msg.set_content("\n".join(a["message"] for a in alerts))
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "25"))) as s:
            if os.getenv("SMTP_USER"):
                s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
