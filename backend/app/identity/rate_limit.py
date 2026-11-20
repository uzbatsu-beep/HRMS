"""Database-backed, account+source login failure limiting.

All buckets use HMAC identifiers instead of usernames or IPs. Database UPSERT
is atomic across application processes (PostgreSQL); never trust user-controlled
X-Forwarded-For headers as an identity source.
"""

import hashlib
import hmac
import ipaddress
import math
import socket
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.identity.models import LoginFailureBucket

WINDOW = timedelta(minutes=10)
PAIR_LIMIT = 6
SOURCE_LIMIT = 60
UTC = timezone.utc


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def client_source(request: Request) -> str:
    """Trust an overwritten X-Real-IP only from the resolved internal proxy.

    Uvicorn proxy_headers is disabled. No arbitrary X-Forwarded-For parsing:
    other Docker containers and public callers cannot forge the trusted peer IP.
    """
    peer = request.client.host if request.client and request.client.host else "unknown"
    hostname = settings.trusted_proxy_hostname
    if hostname:
        try:
            trusted_addresses = {
                str(ipaddress.ip_address(addr[4][0]))
                for addr in socket.getaddrinfo(hostname, None)
            }
            canonical_peer = str(ipaddress.ip_address(peer))
            if canonical_peer in trusted_addresses:
                claimed = request.headers.get("x-real-ip", "")
                return str(ipaddress.ip_address(claimed))
        except (OSError, ValueError):
            pass
    return peer


def hashed_bucket(kind: str, value: str) -> str:
    return hmac.new(
        settings.auth_throttle_hmac_key.encode("utf-8"),
        (kind + "\x00" + value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def keys(request: Request, normalized_username: str) -> tuple[str, str]:
    source = client_source(request)
    return (
        hashed_bucket("account-source", source + "\x00" + normalized_username),
        hashed_bucket("source", source),
    )


def require_login_budget(db: Session, request: Request, username: str) -> None:
    now = datetime.now(UTC)
    pair, source = keys(request, username)
    for key, limit in ((pair, PAIR_LIMIT), (source, SOURCE_LIMIT)):
        row = db.execute(
            select(LoginFailureBucket.failure_count, LoginFailureBucket.expires_at)
            .where(LoginFailureBucket.bucket_key == key)
        ).first()
        if row is None:
            continue
        count, expires = row
        if utc(expires) <= now or count < limit:
            continue
        wait = max(1, math.ceil((utc(expires) - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(wait), "Cache-Control": "no-store"},
        )


def _record_one(db: Session, key: str, now: datetime) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert = postgres_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise RuntimeError("Login throttling requires PostgreSQL or SQLite test database")
    table = LoginFailureBucket
    expired = table.expires_at <= now
    stmt = insert(table).values(
        bucket_key=key, failure_count=1, expires_at=now + WINDOW,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.bucket_key],
        set_={
            "failure_count": case((expired, 1), else_=table.failure_count + 1),
            "expires_at": case((expired, now + WINDOW), else_=table.expires_at),
        },
    )
    db.execute(stmt)


def record_failed_login(db: Session, request: Request, username: str) -> None:
    now = datetime.now(UTC)
    # Expired buckets contain only keyed counters and can be purged safely.
    db.execute(delete(LoginFailureBucket).where(LoginFailureBucket.expires_at <= now))
    for key in keys(request, username):
        _record_one(db, key, now)
    # Persist before the caller returns a 401, which otherwise rolls back its transaction.
    db.commit()


def clear_successful_account_bucket(db: Session, request: Request, username: str) -> None:
    pair, _source = keys(request, username)
    # A successful authentication clears the pair, not source-wide abuse history.
    # The caller commits this change together with the newly issued session.
    db.execute(delete(LoginFailureBucket).where(LoginFailureBucket.bucket_key == pair))
