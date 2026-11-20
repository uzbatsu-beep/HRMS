"""Synthetic load probe never targets remote or state-changing endpoints."""

import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "ops" / "load_probe.py"
spec = importlib.util.spec_from_file_location("twm_pilot_load_probe", SOURCE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("url", [
    "https://pilot.example.com/api/v1/health/ready",
    "http://192.168.1.5/api/v1/health/ready",
    "http://127.0.0.1:8000/api/v1/auth/login",
    "http://127.0.0.1:8000/api/v1/work/orders",
    "http://user:password@localhost:8000/api/v1/health/ready",
])
def test_load_probe_refuses_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        module.validate_url(url)


def test_load_probe_percentiles_are_nearest_rank() -> None:
    assert module.percentile_ms([3, 4, 5, 2, 1], 0.95) == 5
    assert module.percentile_ms([3, 4, 5, 2, 1], 0.50) == 3


def test_load_probe_is_bounded() -> None:
    with pytest.raises(ValueError, match="unbounded"):
        module.probe("http://127.0.0.1:8000/api/v1/health/ready", 1001, 1)
