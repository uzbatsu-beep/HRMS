"""Bounded, loopback-only synthetic readiness probe. Never load-test a live plant."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path not in {"/api/v1/health/ready", "/api/v1/health/live"}
        or parsed.query or parsed.fragment or parsed.username or parsed.password
    ):
        raise ValueError("Load probes are restricted to loopback HTTP health endpoints")


def percentile_ms(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("At least one sample is required")
    return sorted(values)[math.ceil(q * len(values)) - 1]


def sample(url: str) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=5) as r:
            ok = r.status == 200
            r.read(2048)
    except (HTTPError, URLError, TimeoutError, OSError):
        ok = False
    return (time.perf_counter() - start) * 1000, ok


def probe(url: str, requests: int, concurrency: int) -> dict[str, object]:
    validate_url(url)
    if not 1 <= requests <= 1000 or not 1 <= concurrency <= 32:
        raise ValueError("Refusing unbounded probe: requests 1..1000, concurrency 1..32")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(sample, url) for _ in range(requests)]
        results = [future.result() for future in as_completed(futures)]
    ms = [latency for latency, _ in results]
    errors = sum(1 for _, ok in results if not ok)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "errors": errors,
        "error_rate": round(errors / requests, 4),
        "p50_ms": round(percentile_ms(ms, 0.50), 2),
        "p95_ms": round(percentile_ms(ms, 0.95), 2),
        "max_ms": round(max(ms), 2),
        "elapsed_s": round(time.perf_counter() - started, 2),
        "scope": "synthetic-loopback-readiness-only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded TWM CI readiness latency probe")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8000/api/v1/health/ready"
    )
    parser.add_argument("--requests", type=int, default=160)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--p95-ms", type=float, default=1500.0)
    args = parser.parse_args()
    try:
        report = probe(args.url, args.requests, args.concurrency)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return int(report["errors"] > 0 or report["p95_ms"] > args.p95_ms)


if __name__ == "__main__":
    raise SystemExit(main())
