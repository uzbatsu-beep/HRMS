"""Credential safety regression: mandatory AND rules, dates, revocation and scopes."""

from collections.abc import Generator
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.identity.models import UserAccount
from app.identity.security import hash_password
from app.main import app
from app.credentials.models import CredentialAuditEvent, PersonCredential


PASSWORD = "credential-local-dev-password"


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

    tables = [
        table for table in Base.metadata.sorted_tables
        if table.name != "platform_settings"
    ]
    Base.metadata.create_all(engine, tables=tables)
    db = Session(engine, expire_on_commit=False)
    for username, role in (
        ("cred-admin", "admin"), ("cred-admin2", "admin"),
        ("cred-manager", "manager"), ("cred-viewer", "viewer"),
    ):
        db.add(
            UserAccount(
                username=username, role=role, is_active=True,
                password_hash=hash_password(PASSWORD),
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


def auth(client: TestClient, name: str = "cred-admin") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def post(client: TestClient, path: str, payload: dict, who: str = "cred-admin") -> dict:
    response = client.post(path, headers=auth(client, who), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def seed(client: TestClient) -> dict[str, str]:
    enterprise = post(
        client, "/api/v1/org/enterprises", {"code": "factory", "name": "Factory"},
    )["id"]
    type_id = post(
        client, f"/api/v1/org/enterprises/{enterprise}/types",
        {"code": "section", "name": "Section"},
    )["id"]
    unit = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "automation", "name": "Automation", "type_id": type_id},
    )["id"]
    another = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "robots", "name": "Robots", "type_id": type_id},
    )["id"]
    person = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "E-01", "first_name": "Ivan", "last_name": "Petrov",
            "unit_id": unit, "effective_from": (date.today() - timedelta(days=5)).isoformat(),
        },
    )["id"]
    foreign_person = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "E-02", "first_name": "Alex", "last_name": "Ivanov",
            "unit_id": another,
        },
    )["id"]
    permit = post(
        client, f"/api/v1/credentials/enterprises/{enterprise}/types",
        {
            "code": "electrical-iv", "name": "Electrical safety group IV",
            "kind": "permit", "is_safety_critical": True, "requires_expiry": True,
        },
    )["id"]
    return {
        "enterprise": enterprise, "unit": unit, "other_unit": another,
        "person": person, "other_person": foreign_person, "permit": permit,
    }


def required(client: TestClient, enterprise: str, type_id: str, code: str = "electric") -> dict:
    return post(
        client, f"/api/v1/credentials/enterprises/{enterprise}/requirements",
        {"activity_code": code, "type_id": type_id},
    )


def document(
    client: TestClient, s: dict, days_until_expiry: int = 30,
    type_id: str | None = None, expires_on: str | None = "default",
    who: str = "cred-admin",
) -> dict:
    expiry = (
        (date.today() + timedelta(days=days_until_expiry)).isoformat()
        if expires_on == "default" else expires_on
    )
    return post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/records",
        {
            "person_id": s["person"], "type_id": type_id or s["permit"],
            "document_reference": "CERT-001", "issuer": "Training centre",
            "issued_on": (date.today() - timedelta(days=12)).isoformat(),
            "valid_from": (date.today() - timedelta(days=10)).isoformat(),
            "expires_on": expiry,
        },
        who,
    )


def eligibility(
    client: TestClient, person: str, activity: str = "electric",
    when: date | None = None,
) -> dict:
    url = f"/api/v1/credentials/persons/{person}/eligibility/{activity}"
    response = client.get(url, params={"on": when.isoformat()} if when else None)
    assert response.status_code == 200, response.text
    return response.json()


def review(
    client: TestClient, record_id: str, decision: str = "verified",
    who: str = "cred-admin2",
) -> dict:
    response = client.post(
        f"/api/v1/credentials/records/{record_id}/review",
        headers=auth(client, who),
        json={"decision": decision, "note": "Checked original documentation."},
    )
    assert response.status_code == 200, response.text
    return response.json()


def grant(client: TestClient, user: str, unit: str) -> None:
    auth(client)
    ids = {a["username"]: a["id"] for a in client.get("/api/v1/auth/users").json()}
    post(
        client, "/api/v1/org/scopes",
        {"user_id": ids[user], "unit_id": unit, "include_descendants": True},
    )


def test_fail_closed_without_policy_and_without_verified_document(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    result = eligibility(client, s["person"])
    assert not result["eligible"]
    assert {b["code"] for b in result["blockers"]} == {"NO_POLICY"}
    required(client, s["enterprise"], s["permit"])
    result = eligibility(client, s["person"])
    assert {b["code"] for b in result["blockers"]} == {"MISSING_CREDENTIAL"}
    record = document(client, s)
    assert record["status"] == "pending"
    result = eligibility(client, s["person"])
    assert {b["code"] for b in result["blockers"]} == {"UNVERIFIED_CREDENTIAL"}
    own = client.post(
        f"/api/v1/credentials/records/{record['id']}/review",
        headers=auth(client),
        json={"decision": "verified", "note": "I want to approve own submission."},
    )
    assert own.status_code == 403
    reviewed = review(client, record["id"])
    assert reviewed["status"] == "verified"
    result = eligibility(client, s["person"])
    assert result["eligible"] is True
    assert result["blockers"] == []
    assert len(result["valid_credentials"]) == 1
    assert result["valid_credentials"][0]["credential_id"] == record["id"]


def test_expiration_is_inclusive_and_future_check_blocks(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    required(client, s["enterprise"], s["permit"])
    record = document(client, s, days_until_expiry=0)
    review(client, record["id"])
    assert eligibility(client, s["person"])["eligible"]
    future = eligibility(client, s["person"], when=date.today() + timedelta(days=1))
    assert not future["eligible"]
    assert {b["code"] for b in future["blockers"]} == {"EXPIRED_CREDENTIAL"}


def test_revocation_is_immediate_terminal_and_auditable(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    required(client, s["enterprise"], s["permit"])
    record = document(client, s)
    review(client, record["id"])
    result = client.post(
        f"/api/v1/credentials/records/{record['id']}/revoke",
        headers=auth(client, "cred-manager"),
        json={"reason": "Safety training no longer valid."},
    )
    assert result.status_code == 403
    revoked = client.post(
        f"/api/v1/credentials/records/{record['id']}/revoke",
        headers=auth(client),
        json={"reason": "Formal revocation of electrical work authorization."},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    result = eligibility(client, s["person"])
    assert not result["eligible"]
    assert {b["code"] for b in result["blockers"]} == {"REVOKED_CREDENTIAL"}
    assert client.post(
        f"/api/v1/credentials/records/{record['id']}/revoke",
        headers=auth(client), json={"reason": "Should never be silently repeated."},
    ).status_code == 409
    assert client.post(
        f"/api/v1/credentials/records/{record['id']}/review",
        headers=auth(client, "cred-admin2"),
        json={"decision": "verified", "note": "Try to reapprove a revoked document."},
    ).status_code == 409
    events = db.scalars(select(CredentialAuditEvent)).all()
    assert {e.action for e in events} >= {
        "credential.submitted", "credential.reviewed", "credential.revoked",
    }


def test_all_mandatory_requirements_are_checked_as_conjunction(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    additional = post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/types",
        {
            "code": "robot-safety", "name": "Robot safety training",
            "kind": "training", "is_safety_critical": True, "requires_expiry": True,
        },
    )
    required(client, s["enterprise"], s["permit"], "robot-maintenance")
    required(client, s["enterprise"], additional["id"], "robot-maintenance")
    first = document(client, s)
    review(client, first["id"])
    partial = eligibility(client, s["person"], "robot-maintenance")
    assert not partial["eligible"]
    assert {b["code"] for b in partial["blockers"]} == {"MISSING_CREDENTIAL"}
    assert len(partial["valid_credentials"]) == 1
    second = document(client, s, type_id=additional["id"])
    review(client, second["id"])
    complete = eligibility(client, s["person"], "robot-maintenance")
    assert complete["eligible"]
    assert len(complete["valid_credentials"]) == 2


def test_cross_enterprise_records_and_missing_safety_expiration_rejected(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    second = post(
        client, "/api/v1/org/enterprises", {"code": "other", "name": "Other"},
    )["id"]
    foreign = post(
        client, f"/api/v1/credentials/enterprises/{second}/types",
        {
            "code": "other", "name": "Other credentials",
            "kind": "certificate", "is_safety_critical": False,
            "requires_expiry": False,
        },
    )["id"]
    csrf = auth(client)
    invalid_type = client.post(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/requirements",
        headers=csrf, json={"activity_code": "electric", "type_id": foreign},
    )
    assert invalid_type.status_code == 422
    bad_type = client.post(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/types",
        headers=csrf,
        json={
            "code": "unsafe", "name": "Unsafe permit",
            "kind": "permit", "is_safety_critical": True, "requires_expiry": False,
        },
    )
    assert bad_type.status_code == 422
    no_expiry = client.post(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/records",
        headers=csrf,
        json={
            "person_id": s["person"], "type_id": s["permit"],
            "issuer": "Issuer", "document_reference": "DOC",
            "issued_on": date.today().isoformat(),
            "valid_from": date.today().isoformat(), "expires_on": None,
        },
    )
    assert no_expiry.status_code == 422
    other_record = client.post(
        f"/api/v1/credentials/enterprises/{second}/records",
        headers=csrf,
        json={
            "person_id": s["person"], "type_id": foreign,
            "issuer": "Issuer", "document_reference": "DOC",
            "issued_on": date.today().isoformat(),
            "valid_from": date.today().isoformat(), "expires_on": None,
        },
    )
    assert other_record.status_code == 422


def test_scoped_review_and_access_to_person_credentials(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    credential = document(client, s)
    grant(client, "cred-manager", s["other_unit"])
    csrf = auth(client, "cred-manager")
    assert client.post(
        f"/api/v1/credentials/records/{credential['id']}/review",
        headers=csrf,
        json={"decision": "verified", "note": "Out of scope reviewer cannot approve."},
    ).status_code == 404
    assert client.get(f"/api/v1/credentials/persons/{s['person']}").status_code == 404
    assert client.get(
        f"/api/v1/credentials/persons/{s['person']}/eligibility/electric"
    ).status_code == 404
    grant(client, "cred-manager", s["unit"])
    csrf = auth(client, "cred-manager")
    assert client.get(f"/api/v1/credentials/persons/{s['person']}").status_code == 200
    reviewed = client.post(
        f"/api/v1/credentials/records/{credential['id']}/review",
        headers=csrf,
        json={"decision": "verified", "note": "The actual training register was checked."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "verified"
    assert client.post(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/types",
        headers=csrf,
        json={
            "code": "invalid", "name": "No", "kind": "training",
            "is_safety_critical": False, "requires_expiry": True,
        },
    ).status_code == 403


def test_archive_and_unassigned_person_never_eligible(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    required(client, s["enterprise"], s["permit"])
    record = document(client, s)
    review(client, record["id"])
    assert eligibility(client, s["person"])["eligible"]
    no_assignment = post(
        client, f"/api/v1/personnel/enterprises/{s['enterprise']}/persons",
        {"employee_code": "E-99", "first_name": "No", "last_name": "Assignment"},
    )["id"]
    result = eligibility(client, no_assignment)
    assert not result["eligible"]
    assert "NO_ASSIGNMENT" in {item["code"] for item in result["blockers"]}
    archived = client.post(
        f"/api/v1/personnel/persons/{s['person']}/archive",
        headers=auth(client),
    )
    assert archived.status_code == 200
    result = eligibility(client, s["person"])
    assert not result["eligible"]
    assert "INACTIVE_PERSON" in {item["code"] for item in result["blockers"]}


def test_unverified_and_rejected_records_do_not_grant_work(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    required(client, s["enterprise"], s["permit"])
    candidate = document(client, s)
    review(client, candidate["id"], decision="rejected")
    answer = eligibility(client, s["person"])
    assert not answer["eligible"]
    assert {x["code"] for x in answer["blockers"]} == {"REJECTED_CREDENTIAL"}
    repeated = client.post(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/requirements",
        headers=auth(client), json={"activity_code": "ELECTRIC", "type_id": s["permit"]},
    )
    assert repeated.status_code == 409
    assert client.get(
        f"/api/v1/credentials/enterprises/{s['enterprise']}/requirements"
    ).status_code == 200
