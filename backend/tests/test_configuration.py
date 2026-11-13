"""Governed configuration: independent approval, temporal versions and tenant-safe fields."""

from collections.abc import Generator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.configuration.models import ConfigurationAudit, ConfigVersion, PersonFieldRevision
from app.database import Base, get_db
from app.identity.models import UserAccount
from app.identity.security import hash_password
from app.main import app

PASSWORD = "configuration-synthetic-test-password"
BASE = "/api/v1/configuration"


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
        ("config-author", "admin"), ("config-reviewer", "admin"),
        ("config-manager", "manager"), ("config-viewer", "viewer"),
        ("config-denied", "viewer"),
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


def login(client: TestClient, who: str = "config-author") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "username": who, "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def post(client: TestClient, path: str, data: dict, who: str = "config-author") -> dict:
    response = client.post(path, json=data, headers=login(client, who))
    assert response.status_code == 201, response.text
    return response.json()


def seed(client: TestClient, db: Session) -> dict[str, str]:
    enterprise = post(client, "/api/v1/org/enterprises", {
        "code": "config-plant", "name": "Config plant",
    })["id"]
    orgtype = post(
        client, f"/api/v1/org/enterprises/{enterprise}/types",
        {"code": "dept", "name": "Department"},
    )["id"]
    first = post(client, f"/api/v1/org/enterprises/{enterprise}/units", {
        "code": "automation", "name": "Automation", "type_id": orgtype,
    })["id"]
    second = post(client, f"/api/v1/org/enterprises/{enterprise}/units", {
        "code": "mechanics", "name": "Mechanics", "type_id": orgtype,
    })["id"]
    people = []
    for idx, unit in enumerate((first, second)):
        p = post(
            client, f"/api/v1/personnel/enterprises/{enterprise}/persons", {
                "employee_code": "CFG-" + str(idx),
                "first_name": "Synthetic", "last_name": "Worker",
                "unit_id": unit, "effective_from": "2020-01-01",
            },
        )
        people.append(p["id"])
    for who, unit in (("config-manager", first), ("config-viewer", first)):
        admin = login(client)
        user = db.scalar(select(UserAccount).where(UserAccount.username == who))
        assert user is not None
        response = client.post("/api/v1/org/scopes", headers=admin, json={
            "user_id": str(user.id), "unit_id": unit, "include_descendants": False,
        })
        assert response.status_code == 201, response.text
    return {
        "enterprise": enterprise, "unit": first, "other_unit": second,
        "person": people[0], "other_person": people[1],
    }


def schema() -> dict:
    return {"document": {"fields": [
        {"code": "service_group", "label": "Service group",
         "kind": "choice", "required": True, "options": ["ASU", "Electrical"]},
        {"code": "years_experience", "label": "Years of practice",
         "kind": "integer", "min_value": 0, "max_value": 50},
        {"code": "mentor", "label": "Mentor", "kind": "boolean"},
    ]}}


def create(client: TestClient, enterprise: str, data: dict | None = None) -> dict:
    return post(client, f"{BASE}/enterprises/{enterprise}/versions", data or schema())


def transition(
    client: TestClient, version: str, step: str, who: str = "config-author",
    data: dict | None = None,
) -> TestClient:
    login(client, who)
    return client.post(
        f"{BASE}/versions/{version}/{step}", headers=login(client, who),
        json=data,
    )


def published(client: TestClient, enterprise: str) -> dict:
    row = create(client, enterprise)
    version = row["id"]
    assert transition(client, version, "validate").status_code == 200
    assert transition(client, version, "approve", "config-reviewer").status_code == 200
    result = transition(
        client, version, "publish", data={"effective_on": date.today().isoformat()},
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_workflow_is_dual_control_and_immutable(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    row = create(client, s["enterprise"])
    vid = row["id"]
    assert row["status"] == "draft" and row["version"] == 1
    assert transition(client, vid, "approve", "config-reviewer").status_code == 409
    assert transition(client, vid, "publish").status_code == 409

    response = client.put(
        f"{BASE}/versions/{vid}", json=schema(), headers=login(client),
    )
    assert response.status_code == 200
    assert transition(client, vid, "validate").status_code == 200
    assert transition(client, vid, "approve").status_code == 403
    assert transition(client, vid, "approve", "config-manager").status_code == 403
    assert transition(client, vid, "approve", "config-reviewer").status_code == 200
    assert transition(client, vid, "approve", "config-reviewer").status_code == 409
    assert transition(
        client, vid, "publish",
        data={"effective_on": (date.today() - timedelta(days=1)).isoformat()},
    ).status_code == 422
    assert transition(
        client, vid, "publish", data={"effective_on": date.today().isoformat()},
    ).status_code == 200
    assert client.put(
        f"{BASE}/versions/{vid}", headers=login(client), json=schema(),
    ).status_code == 409
    assert transition(client, vid, "validate").status_code == 409
    assert len(db.scalars(select(ConfigVersion)).all()) == 1
    events = db.scalars(select(ConfigurationAudit)).all()
    assert {"configuration.created", "configuration.published"} <= {
        item.action for item in events
    }


def test_no_draft_leak_future_versions_and_scope_access(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    vid = create(client, s["enterprise"])["id"]
    login(client, "config-manager")
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/active",
    ).json() is None
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/versions",
    ).status_code == 403
    login(client, "config-denied")
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/active",
    ).status_code == 404
    assert transition(client, vid, "validate").status_code == 200
    assert transition(client, vid, "approve", "config-reviewer").status_code == 200
    future = date.today() + timedelta(days=5)
    assert transition(
        client, vid, "publish", data={"effective_on": future.isoformat()},
    ).status_code == 200
    login(client, "config-viewer")
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/active",
    ).json() is None
    assert client.get(f"{BASE}/persons/{s['person']}/fields").json()["fields"] == []
    login(client)
    today_version = published(client, s["enterprise"])
    active = client.get(f"{BASE}/enterprises/{s['enterprise']}/active").json()
    assert active["id"] == today_version["id"]
    assert len(client.get(
        f"{BASE}/enterprises/{s['enterprise']}/versions",
    ).json()) == 2
    # A second publish for the same effective date is rejected under the lock.
    vid3 = create(client, s["enterprise"])["id"]
    transition(client, vid3, "validate")
    transition(client, vid3, "approve", "config-reviewer")
    assert transition(
        client, vid3, "publish", data={"effective_on": date.today().isoformat()},
    ).status_code == 409


def test_field_values_scope_validation_history_and_csrf(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    published(client, s["enterprise"])
    endpoint = f"{BASE}/persons/{s['person']}/fields"
    invalid = [
        {"service_group": "Not a controlled choice"},
        {"service_group": "ASU", "years_experience": 80},
        {"service_group": "ASU", "years_experience": True},
        {"service_group": "ASU", "permit_override": "yes"},
        {},
    ]
    for values in invalid:
        response = client.put(
            endpoint, headers=login(client), json={"values": values},
        )
        assert response.status_code == 422, response.text
    assert client.put(endpoint, json={
        "values": {"service_group": "ASU"},
    }).status_code == 403
    assert client.put(
        endpoint, headers=login(client, "config-manager"),
        json={"values": {"service_group": "ASU"}},
    ).status_code == 403

    for experience in (5, 8):
        response = client.put(endpoint, headers=login(client), json={
            "values": {
                "service_group": "ASU", "years_experience": experience, "mentor": False,
            },
        })
        assert response.status_code == 200, response.text
    assert len(db.scalars(select(PersonFieldRevision)).all()) == 2
    current = client.get(endpoint).json()
    assert current["values"]["years_experience"] == 8
    assert current["values"]["mentor"] is False
    login(client, "config-viewer")
    assert client.get(endpoint).status_code == 200
    assert client.get(
        f"{BASE}/persons/{s['other_person']}/fields",
    ).status_code == 404
    login(client, "config-denied")
    assert client.get(endpoint).status_code == 404

    # A later configuration cannot alter historical snapshots; removed keys
    # are hidden from the active view.
    change = create(client, s["enterprise"], {"document": {"fields": [
        {"code": "service_group", "label": "Group", "kind": "choice",
         "required": True, "options": ["ASU", "Electrical"]},
    ]}})
    transition(client, change["id"], "validate")
    transition(client, change["id"], "approve", "config-reviewer")
    assert transition(
        client, change["id"], "publish",
        data={"effective_on": date.today().isoformat()},
    ).status_code == 409  # cannot replace a published effective date
    # Future publication preserves current schema until the effective date.
    assert transition(
        client, change["id"], "publish", data={
            "effective_on": (date.today() + timedelta(days=1)).isoformat(),
        },
    ).status_code == 200
    assert client.get(endpoint).json()["values"]["years_experience"] == 8


def test_invalid_document_and_enterprise_isolation(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client, db)
    for bad in (
        {"document": {"fields": [{"code": "role", "kind": "text", "label": "Admin"}]}},
        {"document": {"fields": [
            {"code": "same", "label": "A", "kind": "text"},
            {"code": "same", "label": "B", "kind": "boolean"},
        ]}},
        {"document": {"fields": [
            {"code": "choice", "label": "Choices", "kind": "choice", "options": ["one"]},
        ]}},
    ):
        assert client.post(
            f"{BASE}/enterprises/{s['enterprise']}/versions",
            headers=login(client), json=bad,
        ).status_code == 422
    other = post(client, "/api/v1/org/enterprises", {
        "code": "another-enterprise", "name": "Another Enterprise",
    })["id"]
    assert client.get(
        f"{BASE}/enterprises/{other}/versions",
    ).json() == []
    assert client.get(
        f"{BASE}/persons/{s['other_person']}/fields",
    ).status_code == 200
