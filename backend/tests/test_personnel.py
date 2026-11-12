"""Personnel integration tests: tenancy, read scopes, dated transfers and archive."""

from collections.abc import Generator
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.identity.models import LoginSession, UserAccount
from app.identity.security import hash_password
from app.main import app
from app.organization.models import (
    Enterprise,
    OrganizationAuditEvent,
    OrganizationUnit,
    OrganizationUnitType,
    UserUnitScope,
)
from app.personnel.models import (
    EmploymentAssignment,
    Person,
    PersonnelAuditEvent,
    TeamMembership,
    WorkforceResource,
)

PASSWORD = "workforce-test-password"


@pytest.fixture
def personnel_client() -> Generator[tuple[TestClient, Session, dict[str, str]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            UserAccount.__table__,
            LoginSession.__table__,
            Enterprise.__table__,
            OrganizationUnitType.__table__,
            OrganizationUnit.__table__,
            UserUnitScope.__table__,
            OrganizationAuditEvent.__table__,
            Person.__table__,
            WorkforceResource.__table__,
            EmploymentAssignment.__table__,
            TeamMembership.__table__,
            PersonnelAuditEvent.__table__,
        ],
    )
    db = Session(engine, expire_on_commit=False)
    users: dict[str, str] = {}
    for role in ("admin", "manager", "viewer"):
        user = UserAccount(
            username=f"people-{role}",
            password_hash=hash_password(PASSWORD),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        users[role] = str(user.id)
    db.commit()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, db, users
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def login(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"people-{role}", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def environment(client: TestClient) -> tuple[str, str, str, str, str]:
    csrf = login(client, "admin")
    enterprise = client.post(
        "/api/v1/org/enterprises",
        headers=csrf, json={"code": "factory", "name": "Test factory"},
    )
    assert enterprise.status_code == 201, enterprise.text
    enterprise_id = enterprise.json()["id"]
    tp = client.post(
        f"/api/v1/org/enterprises/{enterprise_id}/types",
        headers=csrf, json={"code": "department", "name": "Department"},
    )
    assert tp.status_code == 201, tp.text
    type_id = tp.json()["id"]
    ids = []
    for code in ("automation", "mechanics", "robotics"):
        result = client.post(
            f"/api/v1/org/enterprises/{enterprise_id}/units",
            headers=csrf, json={"code": code, "name": code.upper(), "type_id": type_id},
        )
        assert result.status_code == 201, result.text
        ids.append(result.json()["id"])
    return enterprise_id, ids[0], ids[1], ids[2], type_id


def create_person(
    client: TestClient,
    enterprise_id: str,
    unit_id: str | None,
    code: str = "EMP-101",
    start_on: date | None = None,
) -> dict:
    csrf = login(client, "admin")
    response = client.post(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        headers=csrf,
        json={
            "employee_code": code,
            "first_name": "Анна",
            "last_name": "Петрова",
            "middle_name": "Викторовна",
            "unit_id": unit_id,
            "position_title": "Инженер АСУ ТП",
            "effective_from": (start_on or date.today()).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def grant(client: TestClient, user_id: str, unit_id: str) -> None:
    csrf = login(client, "admin")
    result = client.post(
        "/api/v1/org/scopes", headers=csrf,
        json={"user_id": user_id, "unit_id": unit_id, "include_descendants": True},
    )
    assert result.status_code == 201, result.text


def get_roster(client: TestClient, enterprise_id: str, **params: object) -> list[dict]:
    response = client.get(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons", params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_person_and_resource_are_distinct_and_history_persists(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, db, users = personnel_client
    enterprise_id, automation, _, _, _ = environment(client)
    start = date.today() - timedelta(days=28)
    person = create_person(client, enterprise_id, automation, start_on=start)
    assert person["id"] != person["resource_id"]
    assert person["current_unit_id"] == automation
    assert person["position_title"] == "Инженер АСУ ТП"
    assert len(person["assignments"]) == 1
    assert person["assignments"][0]["effective_from"] == start.isoformat()
    assert person["team_memberships"] == []
    assert db.get(Person, UUID(person["id"])) is not None
    assert db.get(WorkforceResource, UUID(person["resource_id"])) is not None

    duplicate = client.post(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        headers=login(client, "admin"),
        json={
            "employee_code": "emp-101", "first_name": "Other",
            "last_name": "Person", "unit_id": automation,
        },
    )
    assert duplicate.status_code == 409
    assert len(get_roster(client, enterprise_id)) == 1
    assert len(get_roster(client, enterprise_id, q="Петрова")) == 1
    assert len(get_roster(client, enterprise_id, q="not-found")) == 0
    assert len(get_roster(client, enterprise_id, unit_id=automation)) == 1
    assert len(get_roster(client, enterprise_id, limit=1, offset=1)) == 0

    grant(client, users["viewer"], automation)
    login(client, "viewer")
    person_response = client.get(f"/api/v1/personnel/persons/{person['id']}")
    assert person_response.status_code == 200
    assert person_response.json()["employee_code"] == "EMP-101"
    assert client.get(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons", params={"include_archived": True}
    ).status_code == 403


def test_nonadmin_default_deny_and_admin_only_writes(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = personnel_client
    enterprise_id, automation, mechanics, _, _ = environment(client)
    person = create_person(client, enterprise_id, automation)
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 200

    viewer_csrf = login(client, "viewer")
    assert client.get(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons"
    ).status_code == 404
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404
    assert client.patch(
        f"/api/v1/personnel/persons/{person['id']}",
        headers=viewer_csrf, json={"last_name": "Новая"},
    ).status_code == 403
    assert client.post(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        headers=viewer_csrf,
        json={"employee_code": "NO", "first_name": "A", "last_name": "B"},
    ).status_code == 403
    grant(client, users["viewer"], mechanics)
    login(client, "viewer")
    assert get_roster(client, enterprise_id) == []
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404

    grant(client, users["viewer"], automation)
    login(client, "viewer")
    assert len(get_roster(client, enterprise_id)) == 1
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 200
    assert client.get(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        params={"unit_id": str(UUID(int=111))},
    ).status_code == 422
    assert client.get(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        params={"unit_id": mechanics},
    ).status_code == 200  # Granted unit, but no employee there.


def test_transfer_changes_effective_visibility_and_preserves_history(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = personnel_client
    enterprise_id, automation, mechanics, _, _ = environment(client)
    start = date.today() - timedelta(days=40)
    person = create_person(client, enterprise_id, automation, start_on=start)
    grant(client, users["viewer"], automation)
    grant(client, users["manager"], mechanics)
    assert client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/transfer",
        json={"unit_id": mechanics, "effective_on": date.today().isoformat()},
    ).status_code == 403
    csrf = login(client, "admin")
    moved = client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/transfer",
        headers=csrf,
        json={"unit_id": mechanics, "effective_on": date.today().isoformat()},
    )
    assert moved.status_code == 201, moved.text
    assert moved.json()["unit_id"] == mechanics

    login(client, "viewer")
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404
    login(client, "manager")
    detail = client.get(f"/api/v1/personnel/persons/{person['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["current_unit_id"] == mechanics
    assert len(detail.json()["assignments"]) == 1  # Hidden old unit history is not leaked.
    assert detail.json()["assignments"][0]["unit_id"] == mechanics

    csrf = login(client, "admin")
    history = client.get(f"/api/v1/personnel/persons/{person['id']}").json()
    assert len(history["assignments"]) == 2
    previous = next(row for row in history["assignments"] if row["unit_id"] == automation)
    assert previous["effective_to"] == (
        date.today() - timedelta(days=1)
    ).isoformat()
    assert client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/transfer",
        headers=csrf,
        json={"unit_id": mechanics, "effective_on": date.today().isoformat()},
    ).status_code == 409
    assert client.get("/api/v1/personnel/audit").status_code == 200


def test_temporal_overlap_and_cross_enterprise_assignments_rejected(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, db, _ = personnel_client
    enterprise_id, automation, _, _, _ = environment(client)
    person = create_person(
        client, enterprise_id, automation,
        start_on=date.today() - timedelta(days=10),
    )
    csrf = login(client, "admin")
    overlap = client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/assignments",
        headers=csrf,
        json={"unit_id": automation, "effective_from": date.today().isoformat()},
    )
    assert overlap.status_code == 409
    wrong_range = client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/assignments",
        headers=csrf,
        json={
            "unit_id": automation,
            "effective_from": date.today().isoformat(),
            "effective_to": (date.today() - timedelta(days=3)).isoformat(),
        },
    )
    assert wrong_range.status_code == 422
    assert client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/transfer",
        headers=csrf,
        json={"unit_id": automation, "effective_on": date.today().isoformat()},
    ).status_code == 409

    other = client.post(
        "/api/v1/org/enterprises",
        headers=csrf, json={"code": "other", "name": "Other enterprise"},
    ).json()["id"]
    tp = client.post(
        f"/api/v1/org/enterprises/{other}/types",
        headers=csrf, json={"code": "team", "name": "Team"},
    ).json()["id"]
    foreign = client.post(
        f"/api/v1/org/enterprises/{other}/units",
        headers=csrf, json={"code": "line", "name": "Line", "type_id": tp},
    ).json()["id"]
    assert client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/teams",
        headers=csrf,
        json={"unit_id": foreign, "effective_from": date.today().isoformat()},
    ).status_code == 422
    assert client.post(
        f"/api/v1/personnel/enterprises/{enterprise_id}/persons",
        headers=csrf,
        json={
            "employee_code": "EMP-999", "first_name": "А", "last_name": "Б",
            "unit_id": foreign,
        },
    ).status_code == 422
    assert db.scalars(select(EmploymentAssignment)).all()


def test_team_membership_does_not_grant_person_profile_access(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = personnel_client
    enterprise_id, automation, mechanics, _, _ = environment(client)
    person = create_person(client, enterprise_id, automation)
    csrf = login(client, "admin")
    membership = client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/teams",
        headers=csrf,
        json={"unit_id": mechanics, "effective_from": date.today().isoformat()},
    )
    assert membership.status_code == 201, membership.text
    duplicate = client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/teams",
        headers=csrf,
        json={"unit_id": mechanics, "effective_from": date.today().isoformat()},
    )
    assert duplicate.status_code == 409
    grant(client, users["viewer"], mechanics)
    login(client, "viewer")
    assert get_roster(client, enterprise_id) == []
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404

    csrf = login(client, "admin")
    end = client.patch(
        f"/api/v1/personnel/teams/{membership.json()['id']}/close",
        headers=csrf, json={"effective_to": date.today().isoformat()},
    )
    assert end.status_code == 200, end.text
    detail = client.get(f"/api/v1/personnel/persons/{person['id']}").json()
    assert detail["team_memberships"][0]["effective_to"] == date.today().isoformat()


def test_update_and_archive_keep_history_but_hide_from_scoped_users(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, db, users = personnel_client
    enterprise_id, automation, _, _, _ = environment(client)
    person = create_person(client, enterprise_id, automation)
    grant(client, users["manager"], automation)
    csrf = login(client, "admin")

    assert client.patch(
        f"/api/v1/personnel/persons/{person['id']}",
        json={"last_name": "Сидорова"},
    ).status_code == 403
    edited = client.patch(
        f"/api/v1/personnel/persons/{person['id']}",
        headers=csrf, json={"last_name": "Сидорова"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["last_name"] == "Сидорова"
    archived = client.post(
        f"/api/v1/personnel/persons/{person['id']}/archive", headers=csrf,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert get_roster(client, enterprise_id) == []
    assert len(get_roster(client, enterprise_id, include_archived=True)) == 1
    assert db.get(WorkforceResource, UUID(person["resource_id"])).is_active is False
    assert len(db.scalars(select(EmploymentAssignment)).all()) == 1

    login(client, "manager")
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404
    assert get_roster(client, enterprise_id) == []
    csrf = login(client, "admin")
    assert client.post(
        f"/api/v1/personnel/resources/{person['resource_id']}/teams",
        headers=csrf,
        json={"unit_id": automation, "effective_from": date.today().isoformat()},
    ).status_code == 409
    assert {row.action for row in db.scalars(select(PersonnelAuditEvent)).all()} >= {
        "person.created", "person.updated", "person.archived"
    }


def test_future_assignment_does_not_expose_person_early(
    personnel_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = personnel_client
    enterprise_id, automation, _, _, _ = environment(client)
    person = create_person(
        client, enterprise_id, automation,
        start_on=date.today() + timedelta(days=4),
    )
    grant(client, users["viewer"], automation)
    login(client, "viewer")
    assert get_roster(client, enterprise_id) == []
    assert client.get(f"/api/v1/personnel/persons/{person['id']}").status_code == 404
    login(client, "admin")
    detail = client.get(f"/api/v1/personnel/persons/{person['id']}")
    assert detail.status_code == 200
    assert detail.json()["current_unit_id"] is None
    assert len(detail.json()["assignments"]) == 1
