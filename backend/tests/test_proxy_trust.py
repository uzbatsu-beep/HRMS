"""Only the explicitly trusted internal proxy may supply client identity."""

from types import SimpleNamespace
from unittest.mock import patch

from app.identity import rate_limit


def request(source: str, claimed: str) -> SimpleNamespace:
    return SimpleNamespace(
        client=SimpleNamespace(host=source),
        headers={"x-real-ip": claimed, "x-forwarded-for": "8.8.8.8"},
    )


def test_untrusted_proxy_headers_are_not_used(monkeypatch) -> None:
    monkeypatch.setattr(
        rate_limit.settings, "trusted_proxy_hostname", None
    )
    assert rate_limit.client_source(request("192.0.2.20", "203.0.113.7")) == "192.0.2.20"


def test_only_resolved_proxy_may_forward_client_ip(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_hostname", "web")
    addr = [(0, 0, 0, "", ("172.25.0.5", 0))]
    with patch.object(rate_limit.socket, "getaddrinfo", return_value=addr):
        assert rate_limit.client_source(
            request("172.25.0.5", "198.51.100.4")
        ) == "198.51.100.4"
        assert rate_limit.client_source(
            request("172.25.0.7", "198.51.100.4")
        ) == "172.25.0.7"
        assert rate_limit.client_source(
            request("172.25.0.5", "not-an-ip")
        ) == "172.25.0.5"


def test_proxy_dns_failure_falls_back_to_connection_peer(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_hostname", "web")
    with patch.object(rate_limit.socket, "getaddrinfo", side_effect=OSError("DNS missing")):
        assert rate_limit.client_source(request("172.25.0.5", "203.0.113.9")) == "172.25.0.5"
