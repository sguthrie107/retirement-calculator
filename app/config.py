"""Application configuration for runtime and local development."""
import os
from pathlib import Path


def _normalize_database_url(default_url: str) -> str:
    """Normalize Railway-style Postgres URLs for SQLAlchemy."""
    raw_url = os.getenv("DATABASE_URL", default_url)
    return raw_url.replace("postgres://", "postgresql://", 1)


def _get_bool(name: str, default: str = "false") -> bool:
    """Return a boolean environment flag."""
    return os.getenv(name, default).strip().lower() == "true"


def _get_origins(default: str) -> list[str]:
    """Return a normalized list of CORS origins."""
    value = os.getenv("ALLOWED_ORIGINS", default)
    return [origin.strip() for origin in value.split(",") if origin.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATABASE_URL = _normalize_database_url("sqlite:///retirement.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
DEBUG = _get_bool("DEBUG")
ALLOWED_ORIGINS = _get_origins("http://localhost:8000")
