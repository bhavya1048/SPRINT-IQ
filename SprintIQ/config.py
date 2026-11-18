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
    # SQLite database file in the project root
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{basedir / 'sprintiq.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
