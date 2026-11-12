"""Identity API integration tests with an isolated SQLite database.

Only the identity tables are created on SQLite; production migrations run on PostgreSQL.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.identity.models import LoginSession, UserAccount
from app.identity.security import hash_password, hash_session_token, verify_password
from app.main import app


@pytest.fixture
def identity_client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserAccount.__table__.create(engine)
    LoginSession.__table__.create(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(
        UserAccount(
            username="root-admin",
            password_hash=hash_password("excellent-local-password"),
            role="admin",
            is_active=True,
        )
    )
    db.commit()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def login_admin(client: TestClient) -> str:
    result = client.post(
        "/api/v1/auth/login",
        json={"username": "root-admin", "password": "excellent-local-password"},
    )
    assert result.status_code == 200
    assert result.json()["user"]["role"] == "admin"
    assert "httponly" in result.headers["set-cookie"].lower()
    assert "samesite=strict" in result.headers["set-cookie"].lower()
    return result.json()["csrf_token"]


def test_password_uses_argon2id_and_rejects_incorrect_password() -> None:
    hashed = hash_password("a-test-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password("a-test-password", hashed)
    assert not verify_password("incorrect", hashed)
    assert not verify_password("hello", "not-a-valid-hash")


def test_me_requires_login(identity_client: tuple[TestClient, Session]) -> None:
    client, _ = identity_client
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/users").status_code == 401


def test_login_rejects_invalid_password_and_bad_origin(
    identity_client: tuple[TestClient, Session],
) -> None:
    client, _ = identity_client
    invalid = client.post(
        "/api/v1/auth/login",
        json={"username": "root-admin", "password": "wrong"},
    )
    assert invalid.status_code == 401
    blocked = client.post(
        "/api/v1/auth/login",
        json={"username": "root-admin", "password": "excellent-local-password"},
        headers={"Origin": "https://unauthorized.example"},
    )
    assert blocked.status_code == 403


def test_admin_can_create_users_but_csrf_is_required(
    identity_client: tuple[TestClient, Session],
) -> None:
    client, db = identity_client
    csrf = login_admin(client)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["csrf_token"] == csrf

    data = {"username": "technician", "password": "long-enough-password", "role": "viewer"}
    assert client.post("/api/v1/auth/users", json=data).status_code == 403
    response = client.post("/api/v1/auth/users", json=data, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 201
    assert response.json()["username"] == "technician"
    assert "password_hash" not in response.json()
    assert client.post(
        "/api/v1/auth/users", json=data, headers={"X-CSRF-Token": csrf}
    ).status_code == 409

    users = client.get("/api/v1/auth/users")
    assert users.status_code == 200
    assert len(users.json()) == 2
    stored = db.scalar(select(UserAccount).where(UserAccount.username == "technician"))
    assert stored is not None and stored.password_hash != "long-enough-password"


def test_viewer_cannot_list_or_create_users(
    identity_client: tuple[TestClient, Session],
) -> None:
    client, _ = identity_client
    csrf = login_admin(client)
    data = {"username": "viewer1", "password": "password-for-viewer1", "role": "viewer"}
    assert client.post(
        "/api/v1/auth/users", json=data, headers={"X-CSRF-Token": csrf}
    ).status_code == 201
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    viewer_login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer1", "password": "password-for-viewer1"},
    )
    assert viewer_login.status_code == 200
    assert client.get("/api/v1/auth/users").status_code == 403
    assert client.post(
        "/api/v1/auth/users",
        json={"username": "newuser", "password": "a-secure-password"},
        headers={"X-CSRF-Token": viewer_login.json()["csrf_token"]},
    ).status_code == 403


def test_logout_revokes_session_and_prevents_cookie_reuse(
    identity_client: tuple[TestClient, Session],
) -> None:
    client, db = identity_client
    csrf = login_admin(client)
    session_cookie = client.cookies.get("twm_session")
    assert session_cookie is not None
    stored = db.scalar(
        select(LoginSession).where(LoginSession.token_hash == hash_session_token(session_cookie))
    )
    assert stored is not None and stored.token_hash != session_cookie

    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
    ).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("twm_session", session_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_and_inactive_user_are_rejected(
    identity_client: tuple[TestClient, Session],
) -> None:
    client, db = identity_client
    login_admin(client)
    record = db.scalars(select(LoginSession)).first()
    assert record is not None
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.expire_all()
    assert client.get("/api/v1/auth/me").status_code == 401
    record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    user = db.scalar(select(UserAccount).where(UserAccount.username == "root-admin"))
    assert user is not None
    user.is_active = False
    db.commit()
    db.expire_all()
    assert client.get("/api/v1/auth/me").status_code == 401
