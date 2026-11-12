"""Competence regression tests: immutable scales, evidence, RBAC and approved-only matrix."""

from collections.abc import Generator
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.identity.models import UserAccount
from app.identity.security import hash_password
from app.competence.models import PersonSkillAssessment, SkillEvidence, UserPersonLink

PASSWORD = "competence-test-password"


@pytest.fixture
def context() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    for name, role in (
        ("skill-admin", "admin"), ("skill-manager", "manager"),
        ("skill-manager2", "manager"), ("skill-viewer", "viewer"),
    ):
        db.add(
            UserAccount(
                username=name, role=role, is_active=True,
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


def auth(client: TestClient, name: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def admin_post(client: TestClient, url: str, data: dict) -> dict:
    token = auth(client, "skill-admin")
    response = client.post(url, headers=token, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def seed(client: TestClient) -> dict[str, str]:
    ent = admin_post(
        client, "/api/v1/org/enterprises",
        {"code": "factory1", "name": "Factory"},
    )["id"]
    kind = admin_post(
        client, f"/api/v1/org/enterprises/{ent}/types",
        {"code": "unit", "name": "Department"},
    )["id"]
    first = admin_post(
        client, f"/api/v1/org/enterprises/{ent}/units",
        {"code": "asu", "name": "АСУ", "type_id": kind},
    )["id"]
    second = admin_post(
        client, f"/api/v1/org/enterprises/{ent}/units",
        {"code": "mechanics", "name": "Mechanics", "type_id": kind},
    )["id"]
    p1 = admin_post(
        client, f"/api/v1/personnel/enterprises/{ent}/persons",
        {"employee_code": "P001", "first_name": "Ivan", "last_name": "Petrov",
         "unit_id": first, "effective_from": date.today().isoformat()},
    )["id"]
    p2 = admin_post(
        client, f"/api/v1/personnel/enterprises/{ent}/persons",
        {"employee_code": "P002", "first_name": "Irina", "last_name": "Sidorova",
         "unit_id": second, "effective_from": date.today().isoformat()},
    )["id"]
    cat = admin_post(
        client, f"/api/v1/competence/enterprises/{ent}/categories",
        {"code": "plc", "name": "PLC"},
    )["id"]
    scale = admin_post(
        client, f"/api/v1/competence/enterprises/{ent}/scales",
        {"code": "tech", "name": "Technical level", "version": 1,
         "levels": [
             {"ordinal": 0, "label": "No experience"},
             {"ordinal": 1, "label": "Engineer"},
             {"ordinal": 3, "label": "Expert"},
         ]},
    )
    skill = admin_post(
        client, f"/api/v1/competence/enterprises/{ent}/skills",
        {"code": "st", "name": "IEC Structured Text",
         "category_id": cat, "scale_id": scale["id"]},
    )["id"]
    users = client.get("/api/v1/auth/users").json()
    ids = {user["username"]: user["id"] for user in users}
    admin_post(
        client, "/api/v1/org/scopes",
        {"user_id": ids["skill-manager"], "unit_id": first,
         "include_descendants": True},
    )
    admin_post(
        client, "/api/v1/org/scopes",
        {"user_id": ids["skill-manager2"], "unit_id": first,
         "include_descendants": True},
    )
    return {
        "enterprise": ent, "unit": first, "other_unit": second,
        "person": p1, "other_person": p2,
        "category": cat, "scale": scale["id"],
        "level": scale["levels"][1]["id"],
        "other_level": scale["levels"][2]["id"],
        "skill": skill,
        "viewer_user": ids["skill-viewer"],
        "manager_user": ids["skill-manager"],
    }


def evidence() -> list[dict]:
    return [{
        "kind": "observation",
        "description": "Observed independent PLC programming during a commissioning trial.",
        "reference": "TEST-OBS-001",
    }]


def test_catalog_is_configurable_and_versions_immutable(context: tuple[TestClient, Session]) -> None:
    client, _ = context
    s = seed(client)
    nested = admin_post(
        client, f"/api/v1/competence/enterprises/{s['enterprise']}/categories",
        {"code": "motion", "name": "Motion", "parent_id": s["category"]},
    )
    assert nested["parent_id"] == s["category"]
    assert len(client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/categories"
    ).json()) == 2

    invalid = client.post(
        f"/api/v1/competence/enterprises/{s['enterprise']}/scales",
        headers=auth(client, "skill-admin"),
        json={"code": "invalid", "name": "Duplicated", "version": 1,
              "levels": [{"ordinal": 1, "label": "X"}, {"ordinal": 1, "label": "Y"}]},
    )
    assert invalid.status_code == 422
    duplicated = client.post(
        f"/api/v1/competence/enterprises/{s['enterprise']}/scales",
        headers=auth(client, "skill-admin"),
        json={"code": "tech", "name": "Duplicate version", "version": 1,
              "levels": [{"ordinal": 0, "label": "None"}, {"ordinal": 1, "label": "Good"}]},
    )
    assert duplicated.status_code == 409
    second = admin_post(
        client, f"/api/v1/competence/enterprises/{s['enterprise']}/scales",
        {"code": "tech", "name": "New standard", "version": 2,
         "levels": [{"ordinal": 0, "label": "Trainee"}, {"ordinal": 5, "label": "Specialist"}]},
    )
    assert second["version"] == 2
    original = client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/scales"
    ).json()
    assert original[0]["levels"][1]["label"] == "Engineer"
    assert second["levels"][1]["ordinal"] == 5

    same_code = client.post(
        f"/api/v1/competence/enterprises/{s['enterprise']}/skills",
        headers=auth(client, "skill-admin"),
        json={
            "code": "ST", "name": "Repeated", "category_id": nested["id"],
            "scale_id": second["id"],
        },
    )
    assert same_code.status_code == 409


def test_default_deny_cross_tenant_and_wrong_scale(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    other_ent = admin_post(
        client, "/api/v1/org/enterprises",
        {"code": "foreign", "name": "Foreign"},
    )["id"]
    other_cat = admin_post(
        client, f"/api/v1/competence/enterprises/{other_ent}/categories",
        {"code": "foreign", "name": "Other skills"},
    )["id"]

    auth(client, "skill-viewer")
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/skills"
    ).status_code == 404
    auth(client, "skill-manager")
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/skills"
    ).status_code == 200
    assert client.get(
        f"/api/v1/competence/enterprises/{other_ent}/categories"
    ).status_code == 404

    bad = client.post(
        f"/api/v1/competence/persons/{s['person']}/expert-assessments",
        headers=auth(client, "skill-manager"),
        json={"skill_id": s["skill"], "level_id": str(UUID(int=25)), "evidence": evidence()},
    )
    assert bad.status_code == 422
    assert client.post(
        f"/api/v1/competence/persons/{s['other_person']}/expert-assessments",
        headers=auth(client, "skill-manager"),
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    ).status_code == 404
    assert client.post(
        f"/api/v1/competence/enterprises/{s['enterprise']}/skills",
        headers=auth(client, "skill-admin"),
        json={
            "code": "other", "name": "Wrong category",
            "category_id": other_cat, "scale_id": s["scale"],
        },
    ).status_code == 422


def test_self_assessment_cannot_be_forged_or_self_approved(
    context: tuple[TestClient, Session],
) -> None:
    client, db = context
    s = seed(client)
    assert client.post(
        f"/api/v1/competence/persons/{s['person']}/self-assessments",
        headers=auth(client, "skill-viewer"),
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    ).status_code == 403
    link = admin_post(
        client, "/api/v1/competence/links",
        {"user_id": s["viewer_user"], "person_id": s["person"]},
    )
    assert link["person_id"] == s["person"]
    assert db.get(UserPersonLink, UUID(s["viewer_user"])) is not None

    viewer_token = auth(client, "skill-viewer")
    assert client.get("/api/v1/competence/me/link").json()["person_id"] == s["person"]
    assert client.post(
        f"/api/v1/competence/persons/{s['other_person']}/self-assessments",
        headers=viewer_token,
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    ).status_code == 403
    a = client.post(
        f"/api/v1/competence/persons/{s['person']}/self-assessments",
        headers=viewer_token,
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    )
    assert a.status_code == 201, a.text
    assert a.json()["status"] == "pending"
    assert a.json()["source"] == "self"
    assert len(a.json()["evidence"]) == 1
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/matrix"
    ).json() == []
    assert client.post(
        f"/api/v1/competence/assessments/{a.json()['id']}/review",
        headers=viewer_token, json={"decision": "approved", "note": "I agree completely."},
    ).status_code == 403
    assert len(db.scalars(select(SkillEvidence)).all()) == 1
    assert client.get(
        f"/api/v1/competence/persons/{s['person']}/assessments"
    ).json()[0]["status"] == "pending"


def test_independent_review_and_approved_only_matrix(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    admin_post(
        client, "/api/v1/competence/links",
        {"user_id": s["viewer_user"], "person_id": s["person"]},
    )
    token = auth(client, "skill-viewer")
    assessment = client.post(
        f"/api/v1/competence/persons/{s['person']}/self-assessments",
        headers=token,
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    ).json()
    review = client.post(
        f"/api/v1/competence/assessments/{assessment['id']}/review",
        headers=auth(client, "skill-manager"),
        json={"decision": "approved", "note": "Checked live functional test evidence."},
    )
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "approved"
    assert review.json()["reviewed_by"] is not None
    assert client.post(
        f"/api/v1/competence/assessments/{assessment['id']}/review",
        headers=auth(client, "skill-admin"),
        json={"decision": "rejected", "note": "Trying to reverse prior decision."},
    ).status_code == 409
    auth(client, "skill-manager")
    matrix = client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/matrix"
    ).json()
    assert len(matrix) == 1
    assert matrix[0]["person_id"] == s["person"]
    assert matrix[0]["level_ordinal"] == 1

    # A newer unapproved self-rating cannot supersede the verified level.
    newer = client.post(
        f"/api/v1/competence/persons/{s['person']}/self-assessments",
        headers=auth(client, "skill-viewer"),
        json={
            "skill_id": s["skill"], "level_id": s["other_level"],
            "evidence": evidence(),
        },
    )
    assert newer.status_code == 201
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/matrix"
    ).json()[0]["level_ordinal"] == 1


def test_reviewer_must_be_independent_and_evidence_required(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    proposal = client.post(
        f"/api/v1/competence/persons/{s['person']}/expert-assessments",
        headers=auth(client, "skill-manager"),
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": []},
    )
    assert proposal.status_code == 201
    assessment_id = proposal.json()["id"]
    assert client.post(
        f"/api/v1/competence/assessments/{assessment_id}/review",
        headers=auth(client, "skill-manager"),
        json={"decision": "approved", "note": "Attempt to review own submission."},
    ).status_code == 403
    assert client.post(
        f"/api/v1/competence/assessments/{assessment_id}/review",
        headers=auth(client, "skill-admin"),
        json={"decision": "approved", "note": "No documentation was provided."},
    ).status_code == 422
    accepted = client.post(
        f"/api/v1/competence/assessments/{assessment_id}/review",
        headers=auth(client, "skill-admin"),
        json={"decision": "rejected", "note": "No supporting evidence found."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "rejected"
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/matrix"
    ).json() == []


def test_skill_archiving_preserves_history_and_blocks_new_review(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    assessment = admin_post(
        client, f"/api/v1/competence/persons/{s['person']}/expert-assessments",
        {"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    )
    archive = client.post(
        f"/api/v1/competence/skills/{s['skill']}/archive",
        headers=auth(client, "skill-admin"),
    )
    assert archive.status_code == 200
    assert archive.json()["is_active"] is False
    assert client.post(
        f"/api/v1/competence/assessments/{assessment['id']}/review",
        headers=auth(client, "skill-manager"),
        json={"decision": "approved", "note": "I verified their skill previously."},
    ).status_code == 409
    assert client.post(
        f"/api/v1/competence/persons/{s['person']}/expert-assessments",
        headers=auth(client, "skill-manager"),
        json={"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    ).status_code == 422
    assert client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/skills"
    ).json() == []
    assert len(client.get(
        f"/api/v1/competence/persons/{s['person']}/assessments"
    ).json()) == 1


def test_reviewer_scope_must_include_current_primary_assignment(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    assessment = admin_post(
        client, f"/api/v1/competence/persons/{s['other_person']}/expert-assessments",
        {"skill_id": s["skill"], "level_id": s["level"], "evidence": evidence()},
    )
    other = client.post(
        f"/api/v1/competence/assessments/{assessment['id']}/review",
        headers=auth(client, "skill-manager"),
        json={"decision": "approved", "note": "Should not approve another department."},
    )
    assert other.status_code == 404
    approved = client.post(
        f"/api/v1/competence/assessments/{assessment['id']}/review",
        headers=auth(client, "skill-manager2"),
        json={"decision": "approved", "note": "Still not in permitted department."},
    )
    assert approved.status_code == 404


def test_link_conflicts_and_unauthorized_linking(
    context: tuple[TestClient, Session],
) -> None:
    client, _ = context
    s = seed(client)
    assert client.post(
        "/api/v1/competence/links",
        headers=auth(client, "skill-manager"),
        json={"person_id": s["person"], "user_id": s["viewer_user"]},
    ).status_code == 403
    first = admin_post(
        client, "/api/v1/competence/links",
        {"person_id": s["person"], "user_id": s["viewer_user"]},
    )
    assert first["user_id"] == s["viewer_user"]
    assert client.post(
        "/api/v1/competence/links",
        headers=auth(client, "skill-admin"),
        json={"person_id": s["other_person"], "user_id": s["viewer_user"]},
    ).status_code == 409
    assert client.post(
        "/api/v1/competence/links",
        headers=auth(client, "skill-admin"),
        json={"person_id": s["person"], "user_id": s["manager_user"]},
    ).status_code == 409
