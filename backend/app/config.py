
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables prefixed with TWM_."""

    model_config = SettingsConfigDict(
        env_prefix="TWM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TWM API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://twm:change-me-for-local-development@localhost:5432/twm"
    )
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_throttle_hmac_key: str = "development-only-throttle-key"

    @model_validator(mode="after")
    def require_production_throttle_secret(self) -> "Settings":
        if self.app_env not in {"development", "test"} and (
            len(self.auth_throttle_hmac_key) < 32
            or self.auth_throttle_hmac_key == "development-only-throttle-key"
        ):
            raise ValueError(
                "TWM_AUTH_THROTTLE_HMAC_KEY: independent random secret of at least "
                "32 characters required outside development/test"
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
