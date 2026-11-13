"""Operational analytics: data contracts and RBAC regressions (synthetic SQLite)."""

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.availability.models import WorkReservation
from app.credentials.models import PersonCredential
from app.database import Base, get_db
from app.identity.models import UserAccount
from app.identity.security import hash_password
from app.main import app
from app.work.models import WorkOrder

PASSWORD = "dashboard-synthetic-test-password"
BASE = "/api/v1/analytics"
UTC = timezone.utc


@pytest.fixture
def scenario() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine, tables=[
            table for table in Base.metadata.sorted_tables
            if table.name != "platform_settings"
        ],
    )
    db = Session(engine, expire_on_commit=False)
    for name, role in (
        ("ops-admin", "admin"), ("ops-manager", "manager"),
        ("ops-viewer", "viewer"), ("ops-denied", "viewer"),
    ):
        db.add(UserAccount(
            username=name, role=role, is_active=True,
            password_hash=hash_password(PASSWORD),
        ))
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


def login(client: TestClient, name: str = "ops-admin") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def post(client: TestClient, path: str, data: dict) -> dict:
    response = client.post(path, json=data, headers=login(client))
    assert response.status_code == 201, response.text
    return response.json()


def grant(client: TestClient, db: Session, name: str, unit: str) -> None:
    actor = db.scalar(select(UserAccount).where(UserAccount.username == name))
    assert actor is not None
    post(client, "/api/v1/org/scopes", {
        "user_id": str(actor.id),
        "unit_id": unit,
        "include_descendants": False,
    })


def seed(client: TestClient, db: Session) -> dict[str, str]:
    enterprise = post(client, "/api/v1/org/enterprises", {
        "code": "ops-plant", "name": "Dashboard Plant",
    })["id"]
    unit_type = post(client, f"/api/v1/org/enterprises/{enterprise}/types", {
        "code": "service", "name": "Technical services",
    })["id"]
    units = []
    people = []
    for suffix in ("automation", "mechanics"):
        unit = post(client, f"/api/v1/org/enterprises/{enterprise}/units", {
            "code": suffix, "name": suffix, "type_id": unit_type,
        })["id"]
        person = post(
            client, f"/api/v1/personnel/enterprises/{enterprise}/persons", {
                "employee_code": "ops-" + suffix,
                "first_name": "Sample",
                "last_name": suffix,
                "unit_id": unit,
                "effective_from": "2020-01-01",
            },
        )
        units.append(unit)
        people.append(person)

    today = date.today()
    now = datetime.now(UTC)
    admin = db.scalar(
        select(UserAccount).where(UserAccount.username == "ops-admin")
    )
    assert admin is not None
    for i, status in enumerate(("open", "on_hold", "completed")):
        db.add(WorkOrder(
            enterprise_id=UUID(enterprise),
            unit_id=UUID(units[0 if i != 1 else 1]),
            code="ops-order-" + str(i), title="Synthetic order " + str(i),
            activity_code="inspect", starts_at=now,
            ends_at=now + timedelta(hours=1), status=status,
            priority="critical" if status == "on_hold" else "normal",
            created_by=admin.id,
            created_at=now - timedelta(days=1 + i),
            on_hold_at=now - timedelta(hours=1) if status == "on_hold" else None,
            completed_at=now - timedelta(hours=2) if status == "completed" else None,
        ))
    credential_type = post(
        client, f"/api/v1/credentials/enterprises/{enterprise}/types", {
            "code": "ops-permit", "name": "Ops permit", "kind": "permit",
            "is_safety_critical": True, "requires_expiry": True,
        },
    )["id"]
    for i, status, expiry in (
        (0, "verified", today + timedelta(days=10)),
        (0, "pending", today + timedelta(days=20)),
        (1, "verified", today - timedelta(days=1)),
    ):
        db.add(PersonCredential(
            enterprise_id=UUID(enterprise), person_id=UUID(people[i]["id"]),
            type_id=UUID(credential_type),
            document_reference="OPS-" + status + "-" + str(i),
            issuer="Synthetic issuer", issued_on=today - timedelta(days=60),
            valid_from=today - timedelta(days=30), expires_on=expiry,
            status=status, submitted_by=admin.id,
        ))

    t0 = now - timedelta(days=1)
    for cancelled in (False, True):
        db.add(WorkReservation(
            enterprise_id=UUID(enterprise),
            resource_id=UUID(people[0]["resource_id"]),
            starts_at=t0, ends_at=t0 + timedelta(hours=2),
            external_reference="ops-cancelled" if cancelled else "ops-active",
            cancelled_at=now if cancelled else None, created_by=admin.id,
        ))
    db.commit()
    return {
        "enterprise": enterprise, "unit": units[0], "other_unit": units[1],
        "person": people[0]["id"], "resource": people[0]["resource_id"],
    }


def get(client: TestClient, enterprise: str, unit: str | None = None) -> dict:
    params = {"unit_id": unit} if unit else {}
    response = client.get(
        f"{BASE}/enterprises/{enterprise}/summary", params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_anonymous_and_unscoped_accounts_fail_closed(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    login(client, "ops-denied")
    response = client.get(f"{BASE}/enterprises/{s['enterprise']}/summary")
    assert response.status_code == 404
    response = client.get(
        f"{BASE}/enterprises/{s['enterprise']}/summary",
        params={"unit_id": s["unit"]},
    )
    assert response.status_code == 404
    client.post("/api/v1/auth/logout", headers=login(client))
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/summary"
    ).status_code == 401


def test_admin_real_counts_empty_shifts_and_reservations(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    login(client)
    data = get(client, s["enterprise"])
    assert data["period_days"] == 30
    assert data["renewal_days"] == 30
    assert len(data["trends"]) == 30
    assert sum(row["created"] for row in data["trends"]) == 3
    assert sum(row["completed"] for row in data["trends"]) == 1
    assert data["workforce"] == {
        "active_resources": 2,
        "reservable_next_15m": 0,
        "blocked_next_15m": 2,
    }
    assert data["work_orders"]["on_hold"] == 1
    assert data["work_orders"]["in_progress"] == 0
    assert data["holds"][0]["code"] == "ops-order-1"
    assert data["credentials"] == {
        "expiring_within_30d": 1,
        "expired_records": 1,
        "pending_records": 1,
    }
    assert data["workload"]["reserved_hours"] == 2.0
    assert data["workload"]["resources_with_reservations"] == 1


def test_viewer_manager_unit_scoping_and_forbidden_filter(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    grant(client, db, "ops-viewer", s["unit"])
    grant(client, db, "ops-manager", s["other_unit"])

    login(client, "ops-viewer")
    view = get(client, s["enterprise"])
    assert view["workforce"]["active_resources"] == 1
    assert view["work_orders"]["on_hold"] == 0
    assert view["credentials"]["expired_records"] == 0
    assert view["credentials"]["expiring_within_30d"] == 1
    assert view["workload"]["reserved_hours"] == 2.0
    forbidden = client.get(
        f"{BASE}/enterprises/{s['enterprise']}/summary",
        params={"unit_id": s["other_unit"]},
    )
    assert forbidden.status_code == 404

    login(client, "ops-manager")
    result = get(client, s["enterprise"], s["other_unit"])
    assert result["workforce"]["active_resources"] == 1
    assert result["work_orders"]["on_hold"] == 1
    assert result["credentials"]["expired_records"] == 1
    assert result["credentials"]["expiring_within_30d"] == 0
    assert result["workload"]["reserved_hours"] == 0


def test_admin_single_unit_and_empty_enterprise(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    login(client)
    selected = get(client, s["enterprise"], s["unit"])
    assert selected["work_orders"]["on_hold"] == 0
    assert selected["credentials"]["expired_records"] == 0
    assert len(selected["trends"]) == 30

    empty_enterprise = post(client, "/api/v1/org/enterprises", {
        "code": "ops-empty", "name": "Empty enterprise",
    })["id"]
    empty = get(client, empty_enterprise)
    assert empty["workforce"]["active_resources"] == 0
    assert empty["workload"]["reserved_hours"] == 0
    assert sum(row["created"] for row in empty["trends"]) == 0
