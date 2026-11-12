"""Organization API tests: hierarchy, tenancy boundaries, explicit scopes, CSRF, audit."""

from collections.abc import Generator
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

PASSWORD = "local-organization-password"


@pytest.fixture
def org_client() -> Generator[tuple[TestClient, Session, dict[str, str]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
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
        ],
    )
    db = Session(engine, expire_on_commit=False)
    accounts = {}
    for role, username in (
        ("admin", "admin-org"), ("manager", "manager-org"), ("viewer", "viewer-org")
    ):
        account = UserAccount(
            username=username, password_hash=hash_password(PASSWORD),
            role=role, is_active=True,
        )
        db.add(account)
        db.flush()
        accounts[role] = str(account.id)
    db.commit()

    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, db, accounts
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def authenticate(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"{role}-org", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def create_enterprise(client: TestClient, csrf: dict[str, str], code: str) -> dict:
    response = client.post(
        "/api/v1/org/enterprises",
        headers=csrf,
        json={"code": code, "name": f"Enterprise {code}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_type(
    client: TestClient, csrf: dict[str, str], enterprise_id: str, code: str = "department"
) -> dict:
    response = client.post(
        f"/api/v1/org/enterprises/{enterprise_id}/types",
        headers=csrf,
        json={"code": code, "name": code.upper()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_unit(
    client: TestClient, csrf: dict[str, str], enterprise_id: str, type_id: str,
    code: str, parent_id: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/org/enterprises/{enterprise_id}/units",
        headers=csrf,
        json={
            "code": code, "name": code.upper(),
            "type_id": type_id, "parent_id": parent_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def grant(
    client: TestClient, csrf: dict[str, str], user_id: str, unit_id: str,
    include_descendants: bool = True,
) -> dict:
    response = client.post(
        "/api/v1/org/scopes",
        headers=csrf,
        json={
            "user_id": user_id, "unit_id": unit_id,
            "include_descendants": include_descendants,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authentication_and_csrf_are_required(
    org_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, _ = org_client
    assert client.get("/api/v1/org/enterprises").status_code == 401
    assert client.post(
        "/api/v1/org/enterprises", json={"code": "demo", "name": "Demo"}
    ).status_code == 401
    authenticate(client, "admin")
    assert client.post(
        "/api/v1/org/enterprises", json={"code": "demo", "name": "Demo"}
    ).status_code == 403


def test_create_custom_hierarchy_and_reject_cycles(
    org_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, _ = org_client
    csrf = authenticate(client, "admin")
    enterprise = create_enterprise(client, csrf, "factory")
    second = create_enterprise(client, csrf, "second")
    department = create_type(client, csrf, enterprise["id"], "technical_service")
    machine_group = create_type(client, csrf, enterprise["id"], "robotics_team")
    foreign_type = create_type(client, csrf, second["id"], "factory_line")

    root = create_unit(client, csrf, enterprise["id"], department["id"], "service")
    child = create_unit(
        client, csrf, enterprise["id"], machine_group["id"], "robots", root["id"]
    )
    leaf = create_unit(
        client, csrf, enterprise["id"], machine_group["id"], "robots-a", child["id"]
    )

    units = client.get(f"/api/v1/org/enterprises/{enterprise['id']}/units")
    assert units.status_code == 200
    assert {x["code"] for x in units.json()} == {"service", "robots", "robots-a"}
    assert client.get(f"/api/v1/org/units/{leaf['id']}").json()["parent_id"] == child["id"]

    same_parent = client.patch(
        f"/api/v1/org/units/{root['id']}",
        headers=csrf, json={"parent_id": root["id"]},
    )
    assert same_parent.status_code == 422
    cycle = client.patch(
        f"/api/v1/org/units/{root['id']}",
        headers=csrf, json={"parent_id": leaf["id"]},
    )
    assert cycle.status_code == 422
    foreign = client.post(
        f"/api/v1/org/enterprises/{enterprise['id']}/units",
        headers=csrf,
        json={"code": "wrong", "name": "Wrong", "type_id": foreign_type["id"]},
    )
    assert foreign.status_code == 422
    wrong_parent = client.post(
        f"/api/v1/org/enterprises/{second['id']}/units",
        headers=csrf,
        json={
            "code": "wrong", "name": "Wrong",
            "type_id": foreign_type["id"], "parent_id": root["id"],
        },
    )
    assert wrong_parent.status_code == 422
    assert client.get(f"/api/v1/org/units/{root['id']}").json()["parent_id"] is None

    types = client.get(f"/api/v1/org/enterprises/{enterprise['id']}/types")
    assert {t["code"] for t in types.json()} == {"technical_service", "robotics_team"}
    assert client.patch(
        f"/api/v1/org/units/{leaf['id']}",
        headers=csrf, json={"name": "New name", "parent_id": None},
    ).status_code == 200
    assert client.get(f"/api/v1/org/units/{leaf['id']}").json()["name"] == "New name"


def test_explicit_scope_filters_enterprises_subtrees_and_detail(
    org_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = org_client
    csrf = authenticate(client, "admin")
    e = create_enterprise(client, csrf, "factory")
    e2 = create_enterprise(client, csrf, "another")
    t = create_type(client, csrf, e["id"])
    t2 = create_type(client, csrf, e2["id"])
    root = create_unit(client, csrf, e["id"], t["id"], "service")
    allowed = create_unit(client, csrf, e["id"], t["id"], "allowed", root["id"])
    leaf = create_unit(client, csrf, e["id"], t["id"], "leaf", allowed["id"])
    other = create_unit(client, csrf, e["id"], t["id"], "secret", root["id"])
    hidden = create_unit(client, csrf, e2["id"], t2["id"], "hidden")

    viewer_csrf = authenticate(client, "viewer")
    assert client.get("/api/v1/org/enterprises").json() == []
    assert client.get(f"/api/v1/org/enterprises/{e['id']}/units").status_code == 404
    assert client.get(f"/api/v1/org/units/{leaf['id']}").status_code == 404
    assert client.get(f"/api/v1/org/units/{hidden['id']}").status_code == 404
    assert client.get("/api/v1/org/scopes").status_code == 403
    assert client.post(
        "/api/v1/org/enterprises",
        headers=viewer_csrf,
        json={"code": "illegal", "name": "Illegal"},
    ).status_code == 403

    csrf = authenticate(client, "admin")
    grant(client, csrf, users["viewer"], allowed["id"], include_descendants=True)
    authenticate(client, "viewer")
    enterprises = client.get("/api/v1/org/enterprises").json()
    assert [x["id"] for x in enterprises] == [e["id"]]

    view = client.get(f"/api/v1/org/enterprises/{e['id']}/units")
    assert view.status_code == 200
    assert {x["id"] for x in view.json()} == {allowed["id"], leaf["id"]}
    selected = next(x for x in view.json() if x["id"] == allowed["id"])
    assert selected["parent_id"] is None  # Do not reveal hidden ancestors in response.
    assert client.get(f"/api/v1/org/units/{other['id']}").status_code == 404
    assert client.get(f"/api/v1/org/units/{root['id']}").status_code == 404
    assert client.get(f"/api/v1/org/units/{hidden['id']}").status_code == 404
    assert client.get(f"/api/v1/org/enterprises/{e2['id']}/types").status_code == 404


def test_scope_revoke_exact_grant_and_hierarchy_move_recompute(
    org_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, _, users = org_client
    csrf = authenticate(client, "admin")
    e = create_enterprise(client, csrf, "factory")
    t = create_type(client, csrf, e["id"])
    root = create_unit(client, csrf, e["id"], t["id"], "root")
    sibling = create_unit(client, csrf, e["id"], t["id"], "sibling")
    child = create_unit(client, csrf, e["id"], t["id"], "child", root["id"])
    g = grant(client, csrf, users["manager"], root["id"], include_descendants=False)

    authenticate(client, "manager")
    assert {u["id"] for u in client.get(
        f"/api/v1/org/enterprises/{e['id']}/units"
    ).json()} == {root["id"]}
    assert client.get(f"/api/v1/org/units/{child['id']}").status_code == 404

    csrf = authenticate(client, "admin")
    assert client.delete(f"/api/v1/org/scopes/{g['id']}").status_code == 403
    assert client.delete(
        f"/api/v1/org/scopes/{g['id']}", headers=csrf
    ).status_code == 204
    assert client.delete(
        f"/api/v1/org/scopes/{g['id']}", headers=csrf
    ).status_code == 404
    g = grant(client, csrf, users["manager"], root["id"])
    assert client.post(
        "/api/v1/org/scopes",
        headers=csrf,
        json={
            "user_id": users["manager"], "unit_id": root["id"],
            "include_descendants": True,
        },
    ).status_code == 409
    authenticate(client, "manager")
    assert client.get(f"/api/v1/org/units/{child['id']}").status_code == 200

    csrf = authenticate(client, "admin")
    moved = client.patch(
        f"/api/v1/org/units/{child['id']}",
        headers=csrf, json={"parent_id": sibling["id"]},
    )
    assert moved.status_code == 200
    authenticate(client, "manager")
    assert client.get(f"/api/v1/org/units/{child['id']}").status_code == 404
    assert client.get(f"/api/v1/org/units/{root['id']}").status_code == 200

    csrf = authenticate(client, "admin")
    assert client.get(
        "/api/v1/org/scopes", params={"user_id": users["manager"]}
    ).json()[0]["id"] == g["id"]


def test_conflicts_permissions_and_audit(
    org_client: tuple[TestClient, Session, dict[str, str]],
) -> None:
    client, db, users = org_client
    csrf = authenticate(client, "admin")
    e = create_enterprise(client, csrf, "factory")
    t = create_type(client, csrf, e["id"])
    root = create_unit(client, csrf, e["id"], t["id"], "service")

    assert client.post(
        "/api/v1/org/enterprises",
        headers=csrf, json={"code": "factory", "name": "Duplicate"},
    ).status_code == 409
    assert client.post(
        f"/api/v1/org/enterprises/{e['id']}/types",
        headers=csrf, json={"code": "department", "name": "Duplicate"},
    ).status_code == 409
    assert client.post(
        f"/api/v1/org/enterprises/{e['id']}/units",
        headers=csrf,
        json={"code": "service", "name": "Duplicate", "type_id": t["id"]},
    ).status_code == 409
    assert client.post(
        "/api/v1/org/scopes",
        headers=csrf,
        json={"user_id": users["admin"], "unit_id": root["id"]},
    ).status_code == 422
    assert client.post(
        "/api/v1/org/scopes",
        headers=csrf,
        json={"user_id": str(UUID(int=42)), "unit_id": root["id"]},
    ).status_code == 422

    created_scope = grant(client, csrf, users["viewer"], root["id"])
    assert client.get("/api/v1/org/audit").status_code == 200
    rows = db.scalars(select(OrganizationAuditEvent)).all()
    assert {row.action for row in rows} >= {
        "enterprise.created", "unit_type.created", "unit.created", "scope.granted"
    }
    assert client.delete(
        f"/api/v1/org/scopes/{created_scope['id']}", headers=csrf
    ).status_code == 204
    assert any(row.action == "scope.revoked" for row in db.scalars(
        select(OrganizationAuditEvent)
    ).all())

    authenticate(client, "viewer")
    assert client.get("/api/v1/org/audit").status_code == 403
