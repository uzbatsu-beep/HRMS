
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.main import app


class FakeSession:
    def execute(self, _statement: object) -> int:
        return 1

    def close(self) -> None:
        return None


class UnavailableSession(FakeSession):
    def execute(self, _statement: object) -> int:
        raise SQLAlchemyError("database unavailable")


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_db() -> Generator[FakeSession, None, None]:
        yield FakeSession()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_liveness_is_independent_from_database(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"database": "ok"}}


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    def override_db() -> Generator[UnavailableSession, None, None]:
        yield UnavailableSession()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}
