"""Production pilot configuration must not inherit development security defaults."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import Settings

GOOD_DSN = "postgresql+psycopg://twm:synthetic-strong-passphrase@db:5432/twm"
ORIGIN = "https://twm.example.invalid"


def production(**overrides: object) -> Settings:
    options = {
        "app_env": "production",
        "auth_throttle_hmac_key": "z" * 48,
        "database_url": GOOD_DSN,
        "cors_allowed_origins": ORIGIN,
    }
    options.update(overrides)
    return Settings(**options)


def test_production_requires_independent_throttle_secret() -> None:
    with pytest.raises(ValidationError, match="TWM_AUTH_THROTTLE_HMAC_KEY"):
        production(auth_throttle_hmac_key="development-only-throttle-key")
    with pytest.raises(ValidationError, match="TWM_AUTH_THROTTLE_HMAC_KEY"):
        production(auth_throttle_hmac_key="too-short")
    assert production().auth_throttle_hmac_key == "z" * 48


@pytest.mark.parametrize("database_url", [
    "postgresql+psycopg://twm:change-me-for-local-development@db:5432/twm",
    "postgresql+psycopg://twm:short@db:5432/twm",
    "sqlite:///test.db",
    "postgresql+psycopg://twm@db:5432/twm",
])
def test_production_rejects_unsafe_database_urls(database_url: str) -> None:
    with pytest.raises(ValidationError, match="TWM_DATABASE_URL"):
        production(database_url=database_url)


@pytest.mark.parametrize("origin", [
    "http://twm.example.invalid",
    "*",
    "https://*.example.invalid",
    "https://twm.example.invalid/path",
    "https://twm.example.invalid, http://localhost:5173",
    "",
])
def test_production_rejects_insecure_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="TWM_CORS_ALLOWED_ORIGINS"):
        production(cors_allowed_origins=origin)


def test_production_reads_files_without_logging_values(tmp_path: Path) -> None:
    password = tmp_path / "database"
    hmac = tmp_path / "throttle"
    password.write_text("read-from-file-strong-passphrase\n", encoding="utf-8")
    hmac.write_text("H" * 48 + "\n", encoding="utf-8")
    settings = production(
        database_url="postgresql+psycopg://twm@db:5432/twm",
        database_password_file=str(password),
        auth_throttle_hmac_key_file=str(hmac),
        auth_throttle_hmac_key="development-only-throttle-key",
    )
    assert make_url(settings.database_url).password == "read-from-file-strong-passphrase"
    assert settings.auth_throttle_hmac_key == "H" * 48
    assert "read-from-file-strong-passphrase" not in repr(make_url(settings.database_url))


def test_production_rejects_missing_secret_files(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="TWM_DATABASE_PASSWORD_FILE"):
        production(database_password_file=str(tmp_path / "missing"))
    with pytest.raises(ValidationError, match="TWM_AUTH_THROTTLE_HMAC_KEY_FILE"):
        production(auth_throttle_hmac_key_file="relative-file")


def test_development_allows_documented_local_default() -> None:
    assert Settings(app_env="development").auth_throttle_hmac_key


def test_invalid_environment_fails_closed() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="prod-typo")
