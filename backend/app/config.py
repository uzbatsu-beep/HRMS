"""Fail-closed production settings; development remains isolated and explicit."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def _read_secret_file(path: str, label: str) -> str:
    """Secret paths are absolute, content is never included in errors."""
    file = Path(path)
    if not file.is_absolute() or not file.is_file():
        raise ValueError(f"{label}: an existing absolute secret file is required")
    try:
        secret = file.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise ValueError(f"{label}: unable to read secret file") from exc
    if not secret or "\n" in secret or "\r" in secret:
        raise ValueError(f"{label}: invalid secret file")
    return secret


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables prefixed with TWM_."""

    model_config = SettingsConfigDict(
        env_prefix="TWM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TWM API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://twm:change-me-for-local-development@localhost:5432/twm"
    )
    database_password_file: str | None = None
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_throttle_hmac_key: str = "development-only-throttle-key"
    auth_throttle_hmac_key_file: str | None = None
    trusted_proxy_hostname: str | None = None

    @model_validator(mode="after")
    def validate_runtime_security(self) -> "Settings":
        if self.database_password_file:
            try:
                self.database_url = make_url(self.database_url).set(
                    password=_read_secret_file(
                        self.database_password_file, "TWM_DATABASE_PASSWORD_FILE"
                    )
                ).render_as_string(hide_password=False)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("TWM_DATABASE_URL: invalid PostgreSQL DSN") from exc
        if self.auth_throttle_hmac_key_file:
            self.auth_throttle_hmac_key = _read_secret_file(
                self.auth_throttle_hmac_key_file, "TWM_AUTH_THROTTLE_HMAC_KEY_FILE"
            )

        if self.app_env != "production":
            return self

        if (
            len(self.auth_throttle_hmac_key) < 32
            or self.auth_throttle_hmac_key == "development-only-throttle-key"
        ):
            raise ValueError(
                "TWM_AUTH_THROTTLE_HMAC_KEY: independent secret of at least "
                "32 characters required in production"
            )

        try:
            url = make_url(self.database_url)
        except Exception as exc:
            raise ValueError("TWM_DATABASE_URL: invalid PostgreSQL DSN") from exc
        if (
            url.drivername != "postgresql+psycopg"
            or not url.host or not url.database or not url.username
            or url.password is None or len(url.password) < 16
            or "change-me" in url.password.lower()
        ):
            raise ValueError(
                "TWM_DATABASE_URL: PostgreSQL credentials must be explicit and "
                "non-default in production"
            )
        origins = self.cors_origins
        if not origins:
            raise ValueError("TWM_CORS_ALLOWED_ORIGINS: HTTPS origin is required")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or "*" in origin
            ):
                raise ValueError(
                    "TWM_CORS_ALLOWED_ORIGINS: production requires exact HTTPS origins"
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
