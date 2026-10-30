"""Metadata-only local audit. Not tamper-proof and not an enterprise SIEM."""
import sqlite3
from datetime import datetime, timedelta, timezone
from . import config


def record(user: str, action: str, case_id: str = "") -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.AUDIT_DB_PATH)
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS audit (at TEXT, actor TEXT, action TEXT, case_id TEXT)")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)).isoformat()
            connection.execute("DELETE FROM audit WHERE at < ?", (cutoff,))
            connection.execute("INSERT INTO audit VALUES (?, ?, ?, ?)",
                               (datetime.now(timezone.utc).isoformat(), user, action, case_id))
    finally:
        connection.close()
