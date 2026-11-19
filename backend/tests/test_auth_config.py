"""Development defaults must not silently become production security parameters."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_requires_independent_throttle_secret() -> None:
    with pytest.raises(ValidationError, match="TWM_AUTH_THROTTLE_HMAC_KEY"):
        Settings(app_env="production", auth_throttle_hmac_key="development-only-throttle-key")
    with pytest.raises(ValidationError, match="TWM_AUTH_THROTTLE_HMAC_KEY"):
        Settings(app_env="production", auth_throttle_hmac_key="too-short")
    Settings(app_env="production", auth_throttle_hmac_key="x" * 48)


def test_development_allows_documented_local_default() -> None:
    assert Settings(app_env="development").auth_throttle_hmac_key
