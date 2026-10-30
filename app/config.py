"""Конфигурация прототипа. Значения можно переопределять переменными окружения."""
from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv(override=False)
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VO_DATA_DIR", BASE_DIR / "data"))
STATIC_DIR = Path(os.environ.get("VO_STATIC_DIR", BASE_DIR / "app" / "static"))

UKRF_SANCTIONS_PATH = DATA_DIR / "ukrf_sanctions.json"
SAMPLE_CASES_PATH = DATA_DIR / "sample_cases.json"
USERS_DB_PATH = DATA_DIR / "users.sqlite"
CASES_DB_PATH = DATA_DIR / "cases.sqlite"
ANALYSES_DB_PATH = DATA_DIR / "analyses.sqlite"
AUDIT_DB_PATH = DATA_DIR / "audit.sqlite"

RETENTION_DAYS = int(os.environ.get("VO_RETENTION_DAYS", "30"))
MAX_UPLOAD_MB = int(os.environ.get("VO_MAX_UPLOAD_MB", "20"))
SESSION_TTL_HOURS = 24

DEMO_USER = os.environ.get("VO_DEMO_USER", "demo")
DEMO_PASSWORD = os.environ.get("VO_DEMO_PASSWORD", "demo123")

DISCLAIMER = (
    "Система является вспомогательным инструментом, не принимает судебных решений "
    "и не заменяет судью. Заключение носит справочный характер."
)
