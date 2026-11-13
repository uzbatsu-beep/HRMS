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
from app.personnel.models import EmploymentAssignment, WorkforceResource
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


def test_future_transfer_does_not_expose_out_of_scope_worker(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == UUID(s["foreign_person"]))
    )
    assert resource is not None
    assignment = db.scalar(
        select(EmploymentAssignment).where(EmploymentAssignment.resource_id == resource.id)
    )
    assert assignment is not None
    assignment.effective_to = monday() - timedelta(days=1)
    db.add(EmploymentAssignment(
        enterprise_id=UUID(s["enterprise"]), resource_id=resource.id,
        unit_id=UUID(s["unit"]), effective_from=monday(),
    ))
    db.commit()
    order = create_work(client, s, "future-transfer")
    auth(client)
    users = client.get("/api/v1/auth/users").json()
    manager = next(item for item in users if item["username"] == "wm-manager")
    post(client, "/api/v1/org/scopes", {
        "user_id": manager["id"], "unit_id": s["unit"],
        "include_descendants": True,
    })
    auth(client, "wm-manager")
    response = client.get(f"{BASE}/orders/{order['id']}/candidates")
    assert response.status_code == 200, response.text
    assert s["foreign_person"] not in {x["person_id"] for x in response.json()}
    assert client.get(
        f"{BASE}/orders/{order['id']}/candidates/{s['foreign_person']}"
    ).status_code == 404


def qualified_second_worker(client: TestClient, s: dict) -> None:
    second = {**s, "person": s["other_person"]}
    verified_skills(client, second)
    verified_permit(client, second)


def test_priority_is_audited_and_locked_after_start(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    payload = work_payload(s, "prio-11")
    payload["priority"] = "critical"
    created = post(client, f"{BASE}/enterprises/{s['enterprise']}/orders", payload)
    assert created["priority"] == "critical"
    edited = client.post(
        f"{BASE}/orders/{created['id']}/priority", headers=auth(client),
        json={"priority": "urgent", "reason": "Machine is scheduled next week."},
    )
    assert edited.status_code == 200
    assert edited.json()["priority"] == "urgent"
    assert client.post(
        f"{BASE}/orders/{created['id']}/priority", headers=auth(client),
        json={"priority": "critical", "reason": "          "},
    ).status_code == 422
    assert assign(client, created, s["person"]).status_code == 200
    planned = datetime.fromisoformat(created["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{created['id']}/start", headers=auth(client)
    ).status_code == 200
    assert client.post(
        f"{BASE}/orders/{created['id']}/priority", headers=auth(client),
        json={"priority": "routine", "reason": "A valid reason after start."},
    ).status_code == 409
    actions = {e.action for e in db.scalars(select(WorkAuditEvent)).all()}
    assert "priority.changed" in actions


def test_add_crew_checks_all_gates_and_prevents_double_staffing(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s, "crew-101")
    assert assign(client, work, s["person"]).status_code == 200
    request = {"person_id": s["other_person"], "role": "specialist"}
    missing = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client), json=request
    )
    assert missing.status_code == 409
    assert {x["code"] for x in missing.json()["detail"]["blockers"]} >= {
        "MISSING_VERIFIED_SKILL", "MISSING_CREDENTIAL",
    }
    assert len(db.scalars(select(WorkReservation)).all()) == 1
    qualified_second_worker(client, s)
    created = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client), json=request
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert len(data["crew"]) == 1
    assert data["crew"][0]["role"] == "specialist"
    assert data["crew"][0]["person_id"] == s["other_person"]
    assert db.get(WorkReservation, UUID(data["crew"][0]["reservation_id"])) is not None
    assert client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client), json=request
    ).status_code == 409
    assert client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["person"], "role": "assistant"},
    ).status_code == 409


def test_crew_blocked_by_absence_and_crew_removal_releases_reservation(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    qualified_second_worker(client, s)
    work = create_work(client, s, "crew-leave")
    assert assign(client, work, s["person"]).status_code == 200
    absence = post(
        client, f"/api/v1/availability/resources/{s['other_resource']}/absences",
        {
            "starts_at": interval()[0], "ends_at": interval()[1],
            "category": "training",
        },
    )
    denied = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["other_person"], "role": "assistant"},
    )
    assert denied.status_code == 409
    assert "ABSENT" in {x["code"] for x in denied.json()["detail"]["blockers"]}
    assert client.post(
        f"/api/v1/availability/absences/{absence['id']}/cancel",
        headers=auth(client),
    ).status_code == 200
    added = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["other_person"], "role": "assistant"},
    ).json()
    crew = added["crew"][0]
    removed = client.post(
        f"{BASE}/orders/{work['id']}/crew/{crew['id']}/remove",
        headers=auth(client),
        json={"reason": "Training rescheduled outside planned interval."},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["crew"][0]["removed_at"] is not None
    slot = db.get(WorkReservation, UUID(crew["reservation_id"]))
    assert slot is not None and slot.cancelled_at is not None
    assert client.post(
        f"{BASE}/orders/{work['id']}/crew/{crew['id']}/remove",
        headers=auth(client), json={"reason": "Cannot remove same crew member twice."},
    ).status_code == 404


def test_lead_replacement_is_atomic_and_audited(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    qualified_second_worker(client, s)
    work = create_work(client, s, "lead-replacement")
    initially = assign(client, work, s["person"]).json()
    old_reservation = initially["assignment"]["reservation_id"]
    response = client.post(
        f"{BASE}/orders/{work['id']}/replace-lead", headers=auth(client),
        json={
            "person_id": s["other_person"],
            "reason": "Original specialist is reassigned by supervisor.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignment"]["person_id"] == s["other_person"]
    assert response.json()["assignment"]["reservation_id"] != old_reservation
    assert db.get(WorkReservation, UUID(old_reservation)).cancelled_at is not None
    assert client.post(
        f"{BASE}/orders/{work['id']}/replace-lead", headers=auth(client),
        json={
            "person_id": s["other_person"],
            "reason": "Replacement cannot equal current lead.",
        },
    ).status_code == 409
    assert "lead.replaced" in {
        event.action for event in db.scalars(select(WorkAuditEvent)).all()
    }


def test_start_revalidates_entire_crew_and_cancel_releases_all_reservations(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    qualified_second_worker(client, s)
    work = create_work(client, s, "crew-at-start")
    leader = assign(client, work, s["person"]).json()["assignment"]
    crew_added = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["other_person"], "role": "observer"},
    )
    assert crew_added.status_code == 201
    member = crew_added.json()["crew"][0]
    last = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: last + timedelta(minutes=5))
    # A late absence for just the supporting observer blocks the whole crew.
    post(client, f"/api/v1/availability/resources/{s['other_resource']}/absences", {
        "starts_at": interval()[0], "ends_at": interval()[1],
        "category": "unavailable",
    })
    cannot_start = client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client)
    )
    assert cannot_start.status_code == 409
    assert "ABSENT" in str(cannot_start.json())
    canceled = client.post(
        f"{BASE}/orders/{work['id']}/cancel", headers=auth(client)
    )
    assert canceled.status_code == 200, canceled.text
    for rid in (leader["reservation_id"], member["reservation_id"]):
        slot = db.get(WorkReservation, UUID(rid))
        assert slot is not None and slot.cancelled_at is not None


def test_manual_revalidation_enters_hold_and_refuses_resume_when_revoked(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    permit = verified_permit(client, s)
    work = create_work(client, s, "safety-hold")
    assert assign(client, work, s["person"]).status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client)
    ).status_code == 200
    revoke = client.post(
        f"/api/v1/credentials/records/{permit}/revoke",
        headers=auth(client),
        json={"reason": "Safety permit issuer revoked the qualification."},
    )
    assert revoke.status_code == 200
    diagnosis = client.post(
        f"{BASE}/orders/{work['id']}/revalidate", headers=auth(client)
    )
    assert diagnosis.status_code == 200, diagnosis.text
    result = diagnosis.json()
    assert result["passed"] is False
    assert result["status"] == "on_hold"
    assert "REVOKED_CREDENTIAL" in {
        b["code"] for member in result["members"] for b in member["candidate"]["blockers"]
    }
    assert client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    ).status_code == 409
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Cannot resume without a new verified permit."},
    ).status_code == 409
    assert db.get(WorkOrder, UUID(work["id"])).status == "on_hold"
    assert "safety.hold" in {
        event.action for event in db.scalars(select(WorkAuditEvent)).all()
    }


def test_manual_hold_can_be_resumed_after_valid_recheck(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s, "hold-resume")
    assert assign(client, work, s["person"]).status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client)
    ).status_code == 200
    held = client.post(
        f"{BASE}/orders/{work['id']}/hold", headers=auth(client),
        json={"reason": "Supervisor requested a documented pause for inspection."},
    )
    assert held.status_code == 200, held.text
    assert held.json()["status"] == "on_hold"
    assert client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    ).status_code == 409
    resumed = client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Inspection completed; team credentials rechecked."},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["last_safety_check_at"] is not None
    completed = client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"


def test_viewer_and_csrf_denied_crew_write(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s, "crew-rbac")
    assert assign(client, work, s["person"]).status_code == 200
    assert client.post(
        f"{BASE}/orders/{work['id']}/crew",
        json={"person_id": s["other_person"], "role": "specialist"},
    ).status_code == 403
    assert client.post(
        f"{BASE}/orders/{work['id']}/crew",
        headers=auth(client, "wm-viewer"),
        json={"person_id": s["other_person"], "role": "specialist"},
    ).status_code == 403
    assert client.post(
        f"{BASE}/orders/{work['id']}/hold",
        headers=auth(client, "wm-viewer"),
        json={"reason": "A viewer cannot pause someone else's work."},
    ).status_code == 403


def test_qualified_crew_can_start_and_complete(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    qualified_second_worker(client, s)
    work = create_work(client, s, "crew-success")
    assert assign(client, work, s["person"]).status_code == 200
    added = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["other_person"], "role": "specialist"},
    )
    assert added.status_code == 201, added.text
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    started = client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client)
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"
    check = client.get(f"{BASE}/orders/{work['id']}/safety")
    assert check.status_code == 200, check.text
    assert check.json()["passed"] is True
    assert {member["role"] for member in check.json()["members"]} == {
        "lead", "specialist",
    }
    completed = client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert len(db.scalars(select(WorkReservation)).all()) == 2


def test_invalid_crew_at_completion_persists_safety_hold_without_finishing(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    qualified_second_worker(client, s)
    work = create_work(client, s, "crew-comp-hold")
    assert assign(client, work, s["person"]).status_code == 200
    added = client.post(
        f"{BASE}/orders/{work['id']}/crew", headers=auth(client),
        json={"person_id": s["other_person"], "role": "assistant"},
    )
    assert added.status_code == 201, added.text
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client)
    ).status_code == 200
    post(
        client, f"/api/v1/availability/resources/{s['other_resource']}/absences",
        {
            "starts_at": interval()[0], "ends_at": interval()[1],
            "category": "unavailable",
        },
    )
    denied = client.post(
        f"{BASE}/orders/{work['id']}/complete", headers=auth(client)
    )
    assert denied.status_code == 409, denied.text
    assert "ABSENT" in str(denied.json())
    order = db.get(WorkOrder, UUID(work["id"]))
    db.refresh(order)
    assert order.status == "on_hold"
    assert order.completed_at is None
    assert "safety.hold" in {
        event.action for event in db.scalars(select(WorkAuditEvent)).all()
    }


# PR #17 — linked equipment, credential AND-gates and independent permit workflow.

EQUIPMENT = "/api/v1/equipment"


def add_test_asset(client: TestClient, s: dict, code: str = "machine-17") -> dict:
    return post(client, f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets", {
        "unit_id": s["unit"], "code": code, "name": "Synthetic casting press",
        "kind": "machine", "serial_number": "SYNTHETIC-000",
    })


def link_test_asset(client: TestClient, work: dict, asset: dict) -> dict:
    return post(client, f"{EQUIPMENT}/orders/{work['id']}/equipment", {
        "asset_id": asset["id"],
    })


def prepare_test_permit(
    client: TestClient, work: dict, *,
    checks: bool = True, who: str = "wm-admin",
) -> dict:
    return post(client, f"{EQUIPMENT}/orders/{work['id']}/permit", {
        "hazards_reviewed": checks,
        "energy_isolation_attested": checks,
        "area_access_attested": checks,
        "evidence_reference": "SYNTHETIC-EVIDENCE-001",
    }, who)


def permit_transition(
    client: TestClient, work: dict, permit: dict,
    action: str, who: str = "wm-admin", payload: dict | None = None,
):
    return client.post(
        f"{EQUIPMENT}/orders/{work['id']}/permit/{permit['id']}/{action}",
        headers=auth(client, who), json=payload,
    )


def test_equipment_requires_independent_permit_and_extra_credential(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    asset = add_test_asset(client, s)
    extra = post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/types", {
            "code": "machine-isolation", "name": "Machine-specific training",
            "kind": "training", "is_safety_critical": False,
            "requires_expiry": True,
        },
    )
    requirement = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-credentials",
        headers=auth(client), json={"type_id": extra["id"]},
    )
    assert requirement.status_code == 201, requirement.text
    verified_skills(client, s)
    verified_permit(client, s)
    work = create_work(client, s, "equipment-safety-17")
    attached = link_test_asset(client, work, asset)
    assert attached["asset"]["id"] == asset["id"]
    assert attached["equipment_blockers"] == ["WORK_PERMIT_NOT_APPROVED"]

    missing = check_candidate(client, work, s["person"])
    assert "EQUIPMENT_CREDENTIAL_MISSING" in blockers(missing)
    assert assign(client, work, s["person"]).status_code == 409

    verified_permit(client, {**s, "permit": extra["id"]})
    assigned = assign(client, work, s["person"])
    assert assigned.status_code == 200, assigned.text
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    denied = client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client),
    )
    assert denied.status_code == 409
    assert "WORK_PERMIT_NOT_APPROVED" in {
        x["code"] for x in denied.json()["detail"]["equipment_blockers"]
    }
    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "approve", "wm-reviewer").status_code == 409
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(client, work, permit, "approve").status_code == 403
    assert permit_transition(client, work, permit, "approve", "wm-reviewer").status_code == 200
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client),
    ).status_code == 200

    off = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/state", headers=auth(client),
        json={"status": "out_of_service", "reason": "Synthetic isolation failure review"},
    )
    assert off.status_code == 200
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Synthetic test confirms all gates again"},
    ).status_code == 409

    on = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/state", headers=auth(client),
        json={"status": "active", "reason": "Synthetic equipment restored for test"},
    )
    assert on.status_code == 200
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Synthetic verification of asset reinstatement"},
    ).status_code == 200

    revoked = permit_transition(
        client, work, permit, "revoke", "wm-reviewer",
        {"reason": "Permit withdrawn for synthetic safety test"},
    )
    assert revoked.status_code == 200, revoked.text
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Deliberately invalid previous permit no override"},
    ).status_code == 409
    replacement = prepare_test_permit(client, work)
    assert replacement["version"] == 2
    assert permit_transition(client, work, replacement, "submit").status_code == 200
    assert permit_transition(client, work, replacement, "approve", "wm-reviewer").status_code == 200
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Synthetic replacement approval now in effect"},
    ).status_code == 200
    assert db.scalars(select(WorkOrder)).first() is not None


def test_equipment_scope_and_permit_rejection(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "machine-permissions")
    foreign = post(client, "/api/v1/org/enterprises", {
        "code": "equipment-foreign", "name": "Foreign company",
    })["id"]
    work = create_work(client, s, "permit-auth-17")
    assert client.post(
        f"{EQUIPMENT}/orders/{work['id']}/equipment",
        headers=auth(client), json={"asset_id": s["foreign_person"]},
    ).status_code == 404
    assert client.post(
        f"{EQUIPMENT}/orders/{work['id']}/equipment",
        json={"asset_id": asset["id"]},
    ).status_code == 403
    assert link_test_asset(client, work, asset)["asset"]["code"] == "machine-permissions"
    assert client.post(
        f"{EQUIPMENT}/orders/{work['id']}/equipment",
        headers=auth(client), json={"asset_id": asset["id"]},
    ).status_code == 409
    assert client.get(
        f"{EQUIPMENT}/enterprises/{foreign}/assets",
    ).status_code == 200

    invalid = prepare_test_permit(client, work, checks=False)
    assert permit_transition(client, work, invalid, "submit").status_code == 409
    assert permit_transition(
        client, work, invalid, "revoke", "wm-reviewer",
        {"reason": "Incomplete synthetic hazard checklist"},
    ).status_code == 200
    valid = prepare_test_permit(client, work)
    assert permit_transition(client, work, valid, "submit").status_code == 200

    auth(client, "wm-viewer")
    assert client.get(
        f"{EQUIPMENT}/orders/{work['id']}/safety-package",
    ).status_code == 404
    assert client.post(
        f"{EQUIPMENT}/orders/{work['id']}/permit/{valid['id']}/approve",
        headers=auth(client, "wm-viewer"),
    ).status_code == 403
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).status_code == 404
    auth(client)
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).status_code == 200
    assert db.scalars(select(WorkAuditEvent)).all()


def test_new_asset_requirement_places_active_work_on_software_hold(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "machine-policy-17")
    work = create_work(client, s, "asset-policy-17")
    link_test_asset(client, work, asset)
    assert assign(client, work, s["person"]).status_code == 200
    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(client, work, permit, "approve", "wm-reviewer").status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client),
    ).status_code == 200

    extra = post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/types", {
            "code": "robot-hv", "name": "Additional machine requirement",
            "kind": "training", "requires_expiry": True, "is_safety_critical": False,
        },
    )
    changed = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-credentials",
        json={"type_id": extra["id"]}, headers=auth(client),
    )
    assert changed.status_code == 201, changed.text
    assert client.get(
        f"{BASE}/orders/{work['id']}"
    ).json()["status"] == "on_hold"
    denied = client.post(
        f"{BASE}/orders/{work['id']}/resume",
        headers=auth(client),
        json={"reason": "Attempt to resume without the extra certificate"},
    )
    assert denied.status_code == 409
    assert "EQUIPMENT_CREDENTIAL_MISSING" in str(denied.json())
    verified_permit(client, {**s, "permit": extra["id"]})
    assert client.post(
        f"{BASE}/orders/{work['id']}/resume",
        headers=auth(client),
        json={"reason": "Synthetic follow-up credential now independently verified"},
    ).status_code == 200


# PR #18 — equipment-specific approved skills and scoped software readiness.

def add_equipment_skill(
    client: TestClient, asset: dict, skill_id: str, minimum_id: str,
):
    return client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        headers=auth(client),
        json={"skill_id": skill_id, "min_level_id": minimum_id},
    )


def test_asset_skill_threshold_is_additive_latest_approved_and_not_downgradable(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "machine-skill-18")
    result = add_equipment_skill(client, asset, s["skill"], s["level_high"])
    assert result.status_code == 201, result.text
    assert result.json()["required_skills"][0]["min_ordinal"] == 3
    assert add_equipment_skill(client, asset, s["skill"], s["level_low"]).status_code == 409
    verified_skills(client, s, s["level_low"])
    verified_permit(client, s)
    work = create_work(client, s, "machine-threshold-18")
    link_test_asset(client, work, asset)
    candidate = check_candidate(client, work, s["person"])
    assert "EQUIPMENT_SKILL_BELOW_MINIMUM" in blockers(candidate)
    assert "INSUFFICIENT_SKILL_LEVEL" not in blockers(candidate)
    assert assign(client, work, s["person"]).status_code == 409

    verified_skills(client, s, s["level_high"])
    candidate = check_candidate(client, work, s["person"])
    assert candidate["eligible"] is True
    assert s["skill"] in candidate["verified_skills"]
    verified_skills(client, s, s["level_low"])
    candidate = check_candidate(client, work, s["person"])
    assert "EQUIPMENT_SKILL_BELOW_MINIMUM" in blockers(candidate)


def test_asset_skill_write_rejects_bad_scale_roles_and_scope(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "machine-skills-rbac-18")
    invalid = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        headers=auth(client),
        json={"skill_id": s["skill"], "min_level_id": s["foreign_person"]},
    )
    assert invalid.status_code == 422
    assert client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        json={"skill_id": s["skill"], "min_level_id": s["level_high"]},
    ).status_code == 403
    assert client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        headers=auth(client, "wm-viewer"),
        json={"skill_id": s["skill"], "min_level_id": s["level_high"]},
    ).status_code == 403
    assert client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        headers=auth(client, "wm-manager"),
        json={"skill_id": s["skill"], "min_level_id": s["level_high"]},
    ).status_code == 403
    assert add_equipment_skill(client, asset, s["skill"], s["level_high"]).status_code == 201
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).json()[0]["required_skills"][0]["skill_id"] == s["skill"]


def test_adding_asset_skill_during_running_work_forces_hold_and_rechecks(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "machine-late-skill-18")
    work = create_work(client, s, "work-late-skill-18")
    link_test_asset(client, work, asset)
    assert assign(client, work, s["person"]).status_code == 200
    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(client, work, permit, "approve", "wm-reviewer").status_code == 200
    planned = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: planned + timedelta(minutes=5))
    started = client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client))
    assert started.status_code == 200, started.text

    category = client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/categories",
    ).json()[0]["id"]
    scale = client.get(
        f"/api/v1/competence/enterprises/{s['enterprise']}/scales",
    ).json()[0]
    extra = post(client, f"/api/v1/competence/enterprises/{s['enterprise']}/skills", {
        "code": "robot-teach-18", "name": "Robot teaching test",
        "category_id": category, "scale_id": scale["id"],
    })
    added = add_equipment_skill(client, asset, extra["id"], s["level_high"])
    assert added.status_code == 201, added.text
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    fail = client.post(
        f"{BASE}/orders/{work['id']}/resume",
        headers=auth(client),
        json={"reason": "New machine teaching qualification has not yet been verified"},
    )
    assert fail.status_code == 409
    assert "EQUIPMENT_SKILL_UNVERIFIED" in str(fail.json())
    proposal = post(
        client, f"/api/v1/competence/persons/{s['person']}/expert-assessments", {
            "skill_id": extra["id"], "level_id": s["level_high"],
            "evidence": [{"kind": "observation",
                          "description": "Synthetic robot teach session verified"}],
        },
    )
    assert client.post(
        f"/api/v1/competence/assessments/{proposal['id']}/review",
        headers=auth(client, "wm-reviewer"),
        json={"decision": "approved", "note": "Reviewed synthetic machine teaching skill"},
    ).status_code == 200
    resumed = client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "New asset qualification independently confirmed in system"},
    )
    assert resumed.status_code == 200, resumed.text


def test_scoped_readiness_reports_only_asset_and_permit_software_gates(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "readiness-asset-18")
    work = create_work(client, s, "readiness-job-18")
    link_test_asset(client, work, asset)
    endpoint = f"{EQUIPMENT}/enterprises/{s['enterprise']}/readiness"
    result = client.get(endpoint)
    assert result.status_code == 200, result.text
    report = result.json()
    assert report["total"] == 1 and report["blocked"] == 1
    assert report["on_hold"] == 0
    assert report["items"][0]["software_blockers"] == ["WORK_PERMIT_NOT_APPROVED"]
    assert report["items"][0]["crew_eligibility_checked"] is False
    assert client.get(
        endpoint, params={"unit_id": s["foreign_person"]},
    ).status_code == 404

    manager = next(x for x in client.get("/api/v1/auth/users").json()
                   if x["username"] == "wm-manager")
    post(client, "/api/v1/org/scopes", {
        "user_id": manager["id"], "unit_id": s["unit"],
        "include_descendants": False,
    })
    auth(client, "wm-manager")
    report = client.get(endpoint)
    assert report.status_code == 200
    assert report.json()["total"] == 1
    assert client.get(
        endpoint, params={"unit_id": s["other_unit"]},
    ).status_code == 404
    auth(client, "wm-viewer")
    assert client.get(endpoint).status_code == 404
    auth(client)
    foreign_asset = post(
        client, f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets", {
            "unit_id": s["other_unit"], "code": "readiness-hidden-18",
            "name": "Other-unit test robot", "kind": "robot",
        },
    )
    other_work = create_work(client, s, "readiness-other-unit-18")
    link_test_asset(client, other_work, foreign_asset)
    auth(client, "wm-manager")
    rows = client.get(endpoint).json()
    assert rows["total"] == 1
    auth(client)
    assert client.get(endpoint).json()["total"] == 2
