import os
from pathlib import Path

basedir = Path(__file__).resolve().parent
APP_ENV = os.environ.get("APP_ENV", "development").lower()
SECRET_KEY = os.environ.get("SECRET_KEY")

if APP_ENV == "production" and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured in production.")

class Config:
    SECRET_KEY = SECRET_KEY or "development-only-change-me"
    DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    SESSION_COOKIE_SAMESITE = "Lax"
    ALLOCATION_OVERLOAD_THRESHOLD = 100
    ALLOCATION_UNDERUTILIZED_THRESHOLD = 50
    RISK_DEADLINE_WARNING_DAYS = 5
    RISK_DEADLINE_HIGH_DAYS = 1
    RISK_DEADLINE_MEDIUM_DAYS = 3
    RISK_OVERDUE_MEDIUM_DAYS = 3
    RISK_OVERDUE_HIGH_DAYS = 8
    RISK_OVERLOAD_MEDIUM_PERCENT = 110
    RISK_OVERLOAD_HIGH_PERCENT = 125
    RISK_SPRINT_WARNING_DAYS = 5
    RISK_SPRINT_LOW_LOAD_RATIO = 0.7
    RISK_SPRINT_MEDIUM_LOAD_RATIO = 0.85
    RISK_SPRINT_HIGH_LOAD_RATIO = 1.0
    # SQLite database file in the project root
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{basedir / 'sprintiq.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
