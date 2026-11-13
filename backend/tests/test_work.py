"""Work Management: skills + mandatory permits + shift gates and atomic reservations."""

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
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
from app.availability.models import WorkReservation
from app.credentials.models import PersonCredential
from app.work.models import WorkAuditEvent, WorkOrder, WorkOrderAssignment
from app.work import service as work_service

PASSWORD = "work-order-dev-test-password"
BASE = "/api/v1/work"
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
        ("wm-admin", "admin"), ("wm-reviewer", "admin"),
        ("wm-manager", "manager"), ("wm-viewer", "viewer"),
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


def auth(client: TestClient, name: str = "wm-admin") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def post(client: TestClient, url: str, data: dict, name: str = "wm-admin") -> dict:
    response = client.post(url, json=data, headers=auth(client, name))
    assert response.status_code == 201, response.text
    return response.json()


def monday() -> date:
    now = date.today()
    return now + timedelta(days=(0 - now.weekday()) % 7 + 7)


def interval(start_hour: int = 9, end_hour: int = 10) -> tuple[str, str]:
    day = monday()
    return (
        datetime(day.year, day.month, day.day, start_hour, tzinfo=UTC).isoformat(),
        datetime(day.year, day.month, day.day, end_hour, tzinfo=UTC).isoformat(),
    )


def seed(client: TestClient) -> dict[str, str]:
    enterprise = post(
        client, "/api/v1/org/enterprises",
        {"code": "workplant", "name": "Technical works plant"},
    )["id"]
    unit_type = post(
        client, f"/api/v1/org/enterprises/{enterprise}/types",
        {"code": "dept", "name": "Service"},
    )["id"]
    unit = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "asu", "name": "Automation", "type_id": unit_type},
    )["id"]
    foreign_unit = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "robots", "name": "Robots", "type_id": unit_type},
    )["id"]
    p1 = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "W001", "first_name": "Aleksey", "last_name": "Engineer",
            "unit_id": unit, "effective_from": "2020-01-01",
        },
    )
    p2 = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "W002", "first_name": "Irina", "last_name": "Mechanic",
            "unit_id": unit, "effective_from": "2020-01-01",
        },
    )
    p3 = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "W003", "first_name": "Roman", "last_name": "Roboticist",
            "unit_id": foreign_unit, "effective_from": "2020-01-01",
        },
    )
    category = post(
        client, f"/api/v1/competence/enterprises/{enterprise}/categories",
        {"code": "plc", "name": "PLC"},
    )["id"]
    scale = post(
        client, f"/api/v1/competence/enterprises/{enterprise}/scales",
        {
            "code": "levels", "name": "Technical levels", "version": 1,
            "levels": [
                {"ordinal": 0, "label": "None"},
                {"ordinal": 1, "label": "Qualified"},
                {"ordinal": 3, "label": "Expert"},
            ],
        },
    )
    skill = post(
        client, f"/api/v1/competence/enterprises/{enterprise}/skills",
        {
            "code": "st-programming", "name": "IEC ST Programming",
            "category_id": category, "scale_id": scale["id"],
        },
    )["id"]
    permit = post(
        client, f"/api/v1/credentials/enterprises/{enterprise}/types",
        {
            "code": "plc-work", "name": "Electrical safety permit",
            "kind": "permit", "is_safety_critical": True,
            "requires_expiry": True,
        },
    )["id"]
    post(
        client, f"/api/v1/credentials/enterprises/{enterprise}/requirements",
        {"activity_code": "plc-maintenance", "type_id": permit},
    )
    for resource in (p1["resource_id"], p2["resource_id"], p3["resource_id"]):
        post(
            client, f"/api/v1/availability/resources/{resource}/shifts",
            {
                "weekday": 0, "local_start": "08:00:00", "local_end": "18:00:00",
                "time_zone": "UTC", "valid_from": "2020-01-01",
            },
        )
    return {
        "enterprise": enterprise, "unit": unit, "other_unit": foreign_unit,
        "person": p1["id"], "resource": p1["resource_id"],
        "other_person": p2["id"], "other_resource": p2["resource_id"],
        "foreign_person": p3["id"], "skill": skill,
        "level_low": scale["levels"][1]["id"],
        "level_high": scale["levels"][2]["id"],
        "permit": permit,
    }


def verified_skills(client: TestClient, s: dict, level: str | None = None) -> str:
    proposal = post(
        client, f"/api/v1/competence/persons/{s['person']}/expert-assessments",
        {
            "skill_id": s["skill"], "level_id": level or s["level_high"],
            "evidence": [{
                "kind": "observation", "description": "Commissioning and programming trial",
                "reference": "OBS-ENGINEER-123",
            }],
        },
    )
    result = client.post(
        f"/api/v1/competence/assessments/{proposal['id']}/review",
        headers=auth(client, "wm-reviewer"),
        json={"decision": "approved", "note": "Independently verified demonstration."},
    )
    assert result.status_code == 200, result.text
    return proposal["id"]


def verified_permit(client: TestClient, s: dict, expiry: date | None = None) -> str:
    row = post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/records",
        {
            "person_id": s["person"], "type_id": s["permit"],
            "document_reference": "EL-SAFETY-001", "issuer": "Competent authority",
            "issued_on": (date.today() - timedelta(days=10)).isoformat(),
            "valid_from": (date.today() - timedelta(days=9)).isoformat(),
            "expires_on": (expiry or (monday() + timedelta(days=10))).isoformat(),
        },
    )
    response = client.post(
        f"/api/v1/credentials/records/{row['id']}/review",
        headers=auth(client, "wm-reviewer"),
        json={"decision": "verified", "note": "Original document reviewed by issuer."},
    )
    assert response.status_code == 200, response.text
    return row["id"]


def work_payload(s: dict, code: str = "wo-101") -> dict:
    starts, ends = interval()
    return {
        "code": code, "title": "PLC diagnostic and repair",
        "description": "Check logic, electrical isolation and interlocks.",
        "unit_id": s["unit"], "activity_code": "plc-maintenance",
        "starts_at": starts, "ends_at": ends,
        "required_skills": [{
            "skill_id": s["skill"], "min_level_id": s["level_low"],
        }],
    }


def create_work(client: TestClient, s: dict, code: str = "wo-101") -> dict:
    return post(
        client, f"{BASE}/enterprises/{s['enterprise']}/orders",
        work_payload(s, code),
    )


def check_candidate(client: TestClient, work: dict, person: str) -> dict:
    response = client.get(
        f"{BASE}/orders/{work['id']}/candidates/{person}",
    )
    assert response.status_code == 200, response.text
    return response.json()


def assign(client: TestClient, work: dict, person: str, name: str = "wm-admin"):
    return client.post(
        f"{BASE}/orders/{work['id']}/assign",
        headers=auth(client, name), json={"person_id": person},
    )


def blockers(data: dict) -> set[str]:
    return {row["code"] for row in data["blockers"]}


def test_fail_closed_explains_missing_skill_and_credentials(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    work = create_work(client, s)
    candidate = check_candidate(client, work, s["person"])
    assert candidate["eligible"] is False
    assert {"MISSING_VERIFIED_SKILL", "MISSING_CREDENTIAL"} <= blockers(candidate)
    denied = assign(client, work, s["person"])
    assert denied.status_code == 409, denied.text
    assert {row["code"] for row in denied.json()["detail"]["blockers"]} >= {
        "MISSING_VERIFIED_SKILL", "MISSING_CREDENTIAL",
    }
    auth(client)
    order = client.get(f"{BASE}/orders/{work['id']}").json()
    assert order["status"] == "open" and order["assignment"] is None


def test_combined_gates_reserve_and_reject_duplicate_work(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s)
    candidates = client.get(f"{BASE}/orders/{work['id']}/candidates")
    assert candidates.status_code == 200
    by_id = {item["person_id"]: item for item in candidates.json()}
    assert by_id[s["person"]]["eligible"] is True
    assert by_id[s["other_person"]]["eligible"] is False
    assert check_candidate(client, work, s["person"])["eligible"]
    accepted = assign(client, work, s["person"])
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    assert data["status"] == "assigned"
    assert data["assignment"]["person_id"] == s["person"]
    booking = db.get(WorkReservation, UUID(data["assignment"]["reservation_id"]))
    assert booking is not None and booking.cancelled_at is None
    assert booking.external_reference == f"WO:{work['id']}"
    assert db.scalars(select(WorkOrderAssignment)).one().work_order_id == UUID(work["id"])
    assert assign(client, work, s["person"]).status_code == 409

    second = create_work(client, s, "wo-102")
    other_denied = assign(client, second, s["person"])
    assert other_denied.status_code == 409
    assert "BOOKED" in {b["code"] for b in other_denied.json()["detail"]["blockers"]}
    assert db.get(WorkOrder, UUID(second["id"])).status == "open"


def test_start_rechecks_independent_gates_and_follows_lifecycle(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s)
    accepted = assign(client, work, s["person"])
    assert accepted.status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    started = client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client))
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"
    finished = client.post(f"{BASE}/orders/{work['id']}/complete", headers=auth(client))
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    assert client.post(
        f"{BASE}/orders/{work['id']}/cancel", headers=auth(client)
    ).status_code == 409
    assert client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    ).status_code == 409
    actions = {row.action for row in db.scalars(select(WorkAuditEvent)).all()}
    assert {"work.created", "work.assigned", "work.started", "work.completed"} <= actions


def test_revoked_credential_after_assignment_prevents_start(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    credential_id = verified_permit(client, s)
    work = create_work(client, s)
    assert assign(client, work, s["person"]).status_code == 200
    revoked = client.post(
        f"/api/v1/credentials/records/{credential_id}/revoke",
        headers=auth(client),
        json={"reason": "Issuer formally revoked this safety certificate."},
    )
    assert revoked.status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    denied = client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client))
    assert denied.status_code == 409
    assert "REVOKED_CREDENTIAL" in {
        b["code"] for b in denied.json()["detail"]["blockers"]
    }
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "assigned"


def test_late_absence_blocks_start_and_cancellation_releases_booking(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s)
    assert assign(client, work, s["person"]).status_code == 200
    post(
        client, f"/api/v1/availability/resources/{s['resource']}/absences",
        {
            "starts_at": interval()[0], "ends_at": interval()[1],
            "category": "unavailable",
        },
    )
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    denied = client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client))
    assert denied.status_code == 409
    assert "ABSENT" in {b["code"] for b in denied.json()["detail"]["blockers"]}
    cancel = client.post(f"{BASE}/orders/{work['id']}/cancel", headers=auth(client))
    assert cancel.status_code == 200
    reservation = db.get(
        WorkReservation, UUID(cancel.json()["assignment"]["reservation_id"])
    )
    assert reservation.cancelled_at is not None


def test_wrong_level_and_foreign_skill_cannot_enter_work_policy(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    different_scale = post(
        client, f"/api/v1/competence/enterprises/{s['enterprise']}/scales",
        {
            "code": "alternate", "name": "Wrong scale", "version": 1,
            "levels": [{"ordinal": 0, "label": "Low"}, {"ordinal": 1, "label": "High"}],
        },
    )
    policy = work_payload(s)
    policy["required_skills"][0]["min_level_id"] = different_scale["levels"][1]["id"]
    assert client.post(
        f"{BASE}/enterprises/{s['enterprise']}/orders",
        headers=auth(client), json=policy,
    ).status_code == 422
    policy = work_payload(s)
    policy["required_skills"] = [
        {"skill_id": s["skill"], "min_level_id": s["level_low"]},
        {"skill_id": s["skill"], "min_level_id": s["level_high"]},
    ]
    assert client.post(
        f"{BASE}/enterprises/{s['enterprise']}/orders",
        headers=auth(client), json=policy,
    ).status_code == 422
    policy = work_payload(s)
    policy["required_skills"] = []
    assert client.post(
        f"{BASE}/enterprises/{s['enterprise']}/orders",
        headers=auth(client), json=policy,
    ).status_code == 422


def test_latest_approved_lower_rating_blocks_older_higher_rating(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s, s["level_high"])
    verified_skills(client, s, s["level_low"])
    verified_permit(client, s)
    payload = work_payload(s)
    payload["required_skills"][0]["min_level_id"] = s["level_high"]
    work = post(client, f"{BASE}/enterprises/{s['enterprise']}/orders", payload)
    candidate = check_candidate(client, work, s["person"])
    assert candidate["eligible"] is False
    assert "INSUFFICIENT_SKILL_LEVEL" in blockers(candidate)


def test_credentials_checked_through_last_date_of_work(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    permit_id = verified_permit(client, s)
    # Current verified record expires on Monday, while work ends Tuesday.
    cred = db.get(PersonCredential, UUID(permit_id))
    cred.expires_on = monday()
    db.commit()
    post(
        client, f"/api/v1/availability/resources/{s['resource']}/shifts",
        {
            "weekday": 0, "local_start": "21:00:00", "local_end": "05:00:00",
            "time_zone": "UTC", "valid_from": "2020-01-01",
        },
    )
    policy = work_payload(s, "overnight-1")
    day = monday()
    policy["starts_at"] = datetime(
        day.year, day.month, day.day, 23, tzinfo=UTC
    ).isoformat()
    policy["ends_at"] = datetime(
        (day + timedelta(days=1)).year, (day + timedelta(days=1)).month,
        (day + timedelta(days=1)).day, 1, tzinfo=UTC,
    ).isoformat()
    work = post(client, f"{BASE}/enterprises/{s['enterprise']}/orders", policy)
    result = check_candidate(client, work, s["person"])
    assert "EXPIRED_CREDENTIAL" in blockers(result)
    assert assign(client, work, s["person"]).status_code == 409


def test_scoped_manager_can_dispatch_only_their_unit(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    auth(client, "wm-manager")
    assert client.get(
        f"{BASE}/enterprises/{s['enterprise']}/orders"
    ).status_code == 404
    denied = client.post(
        f"{BASE}/enterprises/{s['enterprise']}/orders",
        headers=auth(client, "wm-manager"), json=work_payload(s),
    )
    assert denied.status_code == 404
    auth(client)
    users = client.get("/api/v1/auth/users").json()
    manager_id = next(row["id"] for row in users if row["username"] == "wm-manager")
    post(
        client, "/api/v1/org/scopes",
        {"user_id": manager_id, "unit_id": s["unit"], "include_descendants": True},
    )
    created = post(
        client, f"{BASE}/enterprises/{s['enterprise']}/orders",
        work_payload(s), "wm-manager",
    )
    auth(client, "wm-manager")
    assert len(client.get(
        f"{BASE}/enterprises/{s['enterprise']}/orders"
    ).json()) == 1
    assert client.get(
        f"{BASE}/orders/{created['id']}/candidates/{s['foreign_person']}"
    ).status_code == 404
    answer = assign(client, created, s["person"], "wm-manager")
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "assigned"
    assert client.post(
        f"{BASE}/orders/{created['id']}/cancel",
        headers=auth(client, "wm-viewer"),
    ).status_code == 403


def test_no_policy_no_credential_and_no_shift_are_independent(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    work = work_payload(s, "unknown-activity")
    work["activity_code"] = "not-configured"
    row = post(client, f"{BASE}/enterprises/{s['enterprise']}/orders", work)
    candidate = check_candidate(client, row, s["person"])
    assert "NO_POLICY" in blockers(candidate)
    assert assign(client, row, s["person"]).status_code == 409
    assert candidate["eligible"] is False


def test_reserved_slot_cannot_be_cancelled_out_of_band_before_start(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s)
    assigned = assign(client, work, s["person"]).json()
    reservation_id = assigned["assignment"]["reservation_id"]
    direct_cancel = client.post(
        f"/api/v1/availability/reservations/{reservation_id}/cancel",
        headers=auth(client),
    )
    assert direct_cancel.status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    result = client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client))
    assert result.status_code == 409
    assert "reservation" in result.json()["detail"].lower()


def test_cross_enterprise_work_is_invisible_and_requires_csrf(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    foreign = post(
        client, "/api/v1/org/enterprises",
        {"code": "other-plant", "name": "Other plant"},
    )["id"]
    payload = work_payload(s)
    assert client.post(
        f"{BASE}/enterprises/{foreign}/orders",
        headers=auth(client), json=payload,
    ).status_code == 404
    no_csrf = client.post(
        f"{BASE}/enterprises/{s['enterprise']}/orders",
        json=payload,
    )
    assert no_csrf.status_code == 403
    work = create_work(client, s)
    assert client.post(
        f"{BASE}/orders/{work['id']}/assign",
        headers=auth(client),
        json={"person_id": s["foreign_person"]},
    ).status_code == 409
    auth(client, "wm-viewer")
    assert client.get(f"{BASE}/orders/{work['id']}").status_code == 404
