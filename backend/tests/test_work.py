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
from app.equipment.models import EquipmentAuditEvent
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


def add_equipment_credential(
    client: TestClient, asset: dict, type_id: str,
):
    proposal = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals",
        headers=auth(client), json={
            "kind": "credential", "credential_type_id": type_id,
            "reason": "Synthetic required equipment credential independently reviewed",
        },
    )
    if proposal.status_code != 201:
        return proposal
    return client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals/{proposal.json()['id']}/approve",
        headers=auth(client, "wm-reviewer"),
        json={"note": "Second administrator approved synthetic equipment policy"},
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
    requirement = add_equipment_credential(client, asset, extra["id"])
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
    changed = add_equipment_credential(client, asset, extra["id"])
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
    proposal = client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals",
        headers=auth(client),
        json={
            "kind": "skill", "skill_id": skill_id,
            "min_level_id": minimum_id,
            "reason": "Synthetic equipment competence policy change for testing",
        },
    )
    if proposal.status_code != 201:
        return proposal
    return client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals/{proposal.json()['id']}/approve",
        headers=auth(client, "wm-reviewer"),
        json={"note": "Reviewed and approved by independent test administrator"},
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
    endpoint = f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals"
    valid = {
        "kind": "skill", "skill_id": s["skill"],
        "min_level_id": s["level_high"],
        "reason": "Synthetic governed robot qualification requirement",
    }
    invalid = client.post(
        endpoint, headers=auth(client),
        json={**valid, "min_level_id": s["foreign_person"]},
    )
    assert invalid.status_code == 422
    assert client.post(endpoint, json=valid).status_code == 403
    assert client.post(
        endpoint, headers=auth(client, "wm-viewer"), json=valid,
    ).status_code == 403
    assert client.post(
        endpoint, headers=auth(client, "wm-manager"), json=valid,
    ).status_code == 403
    assert client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-skills",
        headers=auth(client), json={
            "skill_id": s["skill"], "min_level_id": s["level_high"],
        },
    ).status_code == 409
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


# PR #19 — planned equipment downtime, chronological gates and audit history.

def schedule_downtime(
    client: TestClient, asset: dict, start: datetime, end: datetime,
    reason: str = "Synthetic planned maintenance window for robot",
):
    return client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/downtime",
        headers=auth(client),
        json={
            "starts_at": start.isoformat(),
            "ends_at": end.isoformat(),
            "reason": reason,
        },
    )


def cancel_downtime(client: TestClient, asset: dict, window_id: str):
    return client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/downtime/{window_id}/cancel",
        headers=auth(client),
        json={"reason": "Maintenance was cancelled by authorized test engineer"},
    )


def test_downtime_blocks_matching_is_audited_and_cancelled_window_unblocks(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "maintenance-19")
    work = create_work(client, s, "planned-maint-19")
    link_test_asset(client, work, asset)
    assert check_candidate(client, work, s["person"])["eligible"] is True
    start = datetime.fromisoformat(work["starts_at"])
    end = datetime.fromisoformat(work["ends_at"])

    created = schedule_downtime(
        client, asset, start + timedelta(minutes=10), end - timedelta(minutes=10)
    )
    assert created.status_code == 201, created.text
    window = created.json()
    assert window["cancelled_at"] is None
    assert "EQUIPMENT_DOWNTIME_CONFLICT" in blockers(check_candidate(
        client, work, s["person"]
    ))
    assert assign(client, work, s["person"]).status_code == 409

    package = client.get(f"{EQUIPMENT}/orders/{work['id']}/safety-package").json()
    assert "EQUIPMENT_DOWNTIME_CONFLICT" in package["equipment_blockers"]
    readiness = client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/readiness"
    ).json()
    item = next(row for row in readiness["items"] if row["work_order_id"] == work["id"])
    assert "EQUIPMENT_DOWNTIME_CONFLICT" in item["software_blockers"]

    conflicting = schedule_downtime(
        client, asset, start + timedelta(minutes=20), start + timedelta(minutes=30)
    )
    assert conflicting.status_code == 409
    # Adjacent half-open interval is permitted even while first is active.
    adjacent = schedule_downtime(
        client, asset, end - timedelta(minutes=10), end + timedelta(minutes=15)
    )
    assert adjacent.status_code == 201, adjacent.text

    cancelled = cancel_downtime(client, asset, window["id"])
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancelled_at"] is not None
    assert cancelled.json()["cancel_reason"]
    # The adjacent window begins before job end; it is still a blocker.
    assert "EQUIPMENT_DOWNTIME_CONFLICT" in blockers(check_candidate(
        client, work, s["person"]
    ))
    assert cancel_downtime(client, asset, adjacent.json()["id"]).status_code == 200
    assert check_candidate(client, work, s["person"])["eligible"] is True

    history = client.get(f"{EQUIPMENT}/assets/{asset['id']}/downtime")
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert all(row["cancelled_at"] is not None for row in history.json())
    from app.equipment.models import EquipmentAuditEvent
    actions = {
        row.action for row in db.scalars(select(EquipmentAuditEvent)).all()
    }
    assert {"asset.downtime_scheduled", "asset.downtime_cancelled"} <= actions


def test_downtime_after_start_forces_hold_and_cancel_does_not_auto_resume(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "live-maintenance-19")
    work = create_work(client, s, "active-maintenance-19")
    link_test_asset(client, work, asset)
    assert assign(client, work, s["person"]).status_code == 200
    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(client, work, permit, "approve", "wm-reviewer").status_code == 200
    start = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: start + timedelta(minutes=5))
    assert client.post(f"{BASE}/orders/{work['id']}/start", headers=auth(client)
                       ).status_code == 200

    scheduled = schedule_downtime(
        client, asset, start + timedelta(minutes=20), start + timedelta(minutes=40),
    )
    assert scheduled.status_code == 201, scheduled.text
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    rejected = client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Attempted resume before cancelling maintenance"},
    )
    assert rejected.status_code == 409
    assert "EQUIPMENT_DOWNTIME_CONFLICT" in str(rejected.json())
    cancelled = cancel_downtime(client, asset, scheduled.json()["id"])
    assert cancelled.status_code == 200
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    resumed = client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Authorized human revalidation after cancellation"},
    )
    assert resumed.status_code == 200, resumed.text


def test_downtime_policy_interval_validation_scope_and_csrf(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "maintenance-auth-19")
    start = datetime.fromisoformat(interval()[0])
    end = start + timedelta(hours=1)
    route = f"{EQUIPMENT}/assets/{asset['id']}/downtime"
    valid = {
        "starts_at": start.isoformat(), "ends_at": end.isoformat(),
        "reason": "Scheduled synthetic maintenance of production equipment",
    }
    assert client.post(route, json=valid).status_code == 403
    assert client.post(route, headers=auth(client, "wm-viewer"),
                       json=valid).status_code == 403
    assert client.post(route, headers=auth(client, "wm-manager"),
                       json=valid).status_code == 403
    assert client.post(
        route, headers=auth(client),
        json={**valid, "ends_at": start.isoformat()},
    ).status_code == 422
    assert client.post(
        route, headers=auth(client),
        json={**valid, "ends_at": (start + timedelta(days=15)).isoformat()},
    ).status_code == 422
    assert client.post(
        route, headers=auth(client),
        json={**valid, "reason": "  "},
    ).status_code == 422
    created = client.post(route, headers=auth(client), json=valid)
    assert created.status_code == 201, created.text
    assert client.post(
        route + "/" + created.json()["id"] + "/cancel", json={
            "reason": "Synthetic cancellation requested by maintenance planner",
        }
    ).status_code == 403
    assert client.post(
        route + "/" + created.json()["id"] + "/cancel",
        headers=auth(client, "wm-viewer"),
        json={"reason": "Synthetic cancellation requested by maintenance planner"},
    ).status_code == 403
    auth(client, "wm-viewer")
    assert client.get(route).status_code == 404
    auth(client)
    assert client.get(route).status_code == 200
    cancelled = cancel_downtime(client, asset, created.json()["id"])
    assert cancelled.status_code == 200
    assert cancel_downtime(client, asset, created.json()["id"]).status_code == 409


# PR #20 — redacted, strictly read-only on-demand crew gate snapshot.

def test_equipment_crew_readiness_redacted_and_unchanged_work_state(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "crew-review-20")
    work = create_work(client, s, "crew-inspection-20")
    link_test_asset(client, work, asset)
    endpoint = f"{EQUIPMENT}/orders/{work['id']}/crew-readiness"

    audit_before = len(db.scalars(select(WorkAuditEvent)).all())
    snapshot = client.get(endpoint)
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()
    assert data["gates_passed"] is False
    assert data["leader_assigned"] is False
    assert data["members_checked"] == 0
    assert data["members_blocked"] == 0
    assert data["crew_blocker_codes"] == ["LEADER_NOT_ASSIGNED"]
    assert data["equipment_blocker_codes"] == ["WORK_PERMIT_NOT_APPROVED"]
    assert data["read_only"] is True
    assert data["crew_eligibility_checked"] is True
    assert data["last_persisted_safety_check_at"] is None
    assert {"person_id", "employee_code", "full_name", "members"} \
        .isdisjoint(data.keys())
    assert db.get(WorkOrder, UUID(work["id"])).status == "open"
    assert len(db.scalars(select(WorkAuditEvent)).all()) == audit_before

    verified_skills(client, s)
    credential_id = verified_permit(client, s)
    assert assign(client, work, s["person"]).status_code == 200
    while_unapproved = client.get(endpoint).json()
    assert while_unapproved["members_checked"] == 1
    assert while_unapproved["members_blocked"] == 0
    assert while_unapproved["gates_passed"] is False
    assert while_unapproved["equipment_blocker_codes"] == ["WORK_PERMIT_NOT_APPROVED"]

    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(
        client, work, permit, "approve", "wm-reviewer"
    ).status_code == 200
    passed = client.get(endpoint).json()
    assert passed["leader_assigned"] is True
    assert passed["members_checked"] == 1
    assert passed["members_blocked"] == 0
    assert passed["gates_passed"] is True
    assert passed["equipment_blocker_codes"] == []
    assert passed["crew_blocker_codes"] == []
    assert passed["last_persisted_safety_check_at"] is None

    revoked = client.post(
        f"/api/v1/credentials/records/{credential_id}/revoke",
        headers=auth(client),
        json={"reason": "Synthetic issuer revocation before operational review"},
    )
    assert revoked.status_code == 200
    failed = client.get(endpoint).json()
    assert failed["gates_passed"] is False
    assert failed["members_checked"] == 1
    assert failed["members_blocked"] == 1
    assert "REVOKED_CREDENTIAL" in failed["crew_blocker_codes"]
    assert failed["last_persisted_safety_check_at"] is None
    # Read-side discovery is not a persisted hold or execution authorization.
    order = client.get(f"{BASE}/orders/{work['id']}").json()
    assert order["status"] == "assigned"
    assert order["last_safety_check_at"] is None


def test_equipment_crew_readiness_requires_dispatch_and_both_unit_scopes(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "crew-scope-20")
    work = create_work(client, s, "crew-scope-work-20")
    link_test_asset(client, work, asset)
    endpoint = f"{EQUIPMENT}/orders/{work['id']}/crew-readiness"

    assert client.get(endpoint).status_code == 200
    assert client.get(
        f"{EQUIPMENT}/orders/{s['foreign_person']}/crew-readiness"
    ).status_code == 404
    unlinked = create_work(client, s, "crew-unlinked-20")
    assert client.get(
        f"{EQUIPMENT}/orders/{unlinked['id']}/crew-readiness"
    ).status_code == 404

    auth(client, "wm-viewer")
    assert client.get(endpoint).status_code == 403
    auth(client, "wm-manager")
    assert client.get(endpoint).status_code == 404

    auth(client)
    manager = next(row for row in client.get("/api/v1/auth/users").json()
                   if row["username"] == "wm-manager")
    post(client, "/api/v1/org/scopes", {
        "user_id": manager["id"], "unit_id": s["unit"],
        "include_descendants": False,
    })
    auth(client, "wm-manager")
    assert client.get(endpoint).status_code == 200

    auth(client)
    outside_asset = post(
        client, f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets", {
            "unit_id": s["other_unit"], "code": "crew-invisible-20",
            "name": "Synthetic other-unit servo line", "kind": "production_line",
        },
    )
    outside_work = create_work(client, s, "crew-invisible-work-20")
    link_test_asset(client, outside_work, outside_asset)
    auth(client, "wm-manager")
    assert client.get(
        f"{EQUIPMENT}/orders/{outside_work['id']}/crew-readiness"
    ).status_code == 404
    auth(client)
    assert client.get(
        f"{EQUIPMENT}/orders/{outside_work['id']}/crew-readiness"
    ).status_code == 200


# PR #21 — admin-only bounded redacted equipment audit keyset explorer.

def test_equipment_audit_explorer_keyset_is_stable_and_payload_redacted(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    endpoint = f"{EQUIPMENT}/enterprises/{s['enterprise']}/audit/explorer"
    assets = [
        add_test_asset(client, s, f"audit-explorer-21-{index}")
        for index in range(6)
    ]
    expected = [
        str(row.id)
        for row in db.scalars(
            select(EquipmentAuditEvent).where(
                EquipmentAuditEvent.enterprise_id == UUID(s["enterprise"]),
                EquipmentAuditEvent.action == "asset.created",
            ).order_by(
                EquipmentAuditEvent.created_at.desc(),
                EquipmentAuditEvent.id.desc(),
            )
        ).all()
    ]
    # Existing event table is append-only and filter spans identical timestamps.
    seen: list[str] = []
    cursor: str | None = None
    for index in range(3):
        params = {"action": "asset.created", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = client.get(endpoint, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["enterprise_id"] == s["enterprise"]
        assert page["detail_payloads_included"] is False
        assert len(page["items"]) == 2
        assert page["has_more"] is (index < 2)
        cursor = page["next_cursor"]
        for row in page["items"]:
            assert row["actor_username"] == "wm-admin"
            assert row["action"] == "asset.created"
            assert row["subject_id"] in {asset["id"] for asset in assets}
            assert {"details_json", "evidence_reference", "reason"}.isdisjoint(
                row.keys()
            )
            seen.append(row["id"])
    assert seen == expected
    assert len(set(seen)) == 6
    assert cursor is None

    filtered = client.get(
        endpoint, params={
            "subject_id": assets[0]["id"], "action": "asset.created",
        },
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    actor = filtered.json()["items"][0]["actor_id"]
    actor_filtered = client.get(endpoint, params={"actor_id": actor, "limit": 50})
    assert actor_filtered.status_code == 200
    assert len(actor_filtered.json()["items"]) >= 6
    until = "2000-01-01T00:00:00+00:00"
    assert client.get(endpoint, params={"until": until}).json()["items"] == []


def test_equipment_audit_explorer_scope_validation_and_legacy_compat(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "audit-explorer-scope-21")
    endpoint = f"{EQUIPMENT}/enterprises/{s['enterprise']}/audit/explorer"
    assert client.get(endpoint, params={"limit": 0}).status_code == 422
    assert client.get(endpoint, params={"limit": 51}).status_code == 422
    assert client.get(endpoint, params={"cursor": "not-base64!!"}).status_code == 422
    assert client.get(
        endpoint, params={"cursor": "x" * 181},
    ).status_code == 422
    assert client.get(
        endpoint, params={"since": "2026-01-01T00:00:00"},
    ).status_code == 422
    assert client.get(
        endpoint, params={
            "since": "2026-11-30T12:00:00+00:00",
            "until": "2026-01-01T12:00:00+00:00",
        },
    ).status_code == 422
    assert client.get(
        endpoint, params={"subject_id": s["foreign_person"]},
    ).json()["items"] == []
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['foreign_person']}/audit/explorer"
    ).status_code == 404
    auth(client, "wm-manager")
    assert client.get(endpoint).status_code == 403
    auth(client, "wm-viewer")
    assert client.get(endpoint).status_code == 403
    auth(client)
    legacy = client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/audit",
    )
    assert legacy.status_code == 200
    assert "details_json" in legacy.json()[0]
    current = client.get(endpoint)
    assert current.status_code == 200
    assert "details_json" not in current.json()["items"][0]
    assert current.json()["items"][0]["subject_id"] == asset["id"]


# PR #22 — independent additive equipment policy governance.

def test_governed_policy_is_inactive_before_independent_review_and_reject_preserves_rules(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "policy-review-22")
    work = create_work(client, s, "policy-review-work-22")
    link_test_asset(client, work, asset)
    assert check_candidate(client, work, s["person"])["eligible"] is True
    route = f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals"
    body = {
        "kind": "skill", "skill_id": s["skill"],
        "min_level_id": s["level_high"],
        "reason": "Engineering assessment requires advanced qualification level",
    }
    proposed = client.post(route, headers=auth(client), json=body)
    assert proposed.status_code == 201, proposed.text
    row = proposed.json()
    assert row["status"] == "pending" and row["reviewed_by"] is None
    assert row["proposed_by"]
    assert check_candidate(client, work, s["person"])["eligible"] is True
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).json()[0]["required_skills"] == []
    assert client.post(route, headers=auth(client), json=body).status_code == 409
    review_route = route + "/" + row["id"]
    review = {"note": "Independent review of equipment policy justification"}
    assert client.post(
        review_route + "/approve", headers=auth(client), json=review,
    ).status_code == 403
    assert client.post(
        review_route + "/reject", headers=auth(client), json=review,
    ).status_code == 403
    assert client.post(
        review_route + "/approve", headers=auth(client, "wm-manager"), json=review,
    ).status_code == 403
    assert client.post(
        review_route + "/approve", json=review,
    ).status_code == 403
    rejected = client.post(
        review_route + "/reject", headers=auth(client, "wm-reviewer"), json=review,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reviewed_by"] != rejected.json()["proposed_by"]
    assert client.post(
        review_route + "/approve", headers=auth(client, "wm-reviewer"), json=review,
    ).status_code == 409
    assert check_candidate(client, work, s["person"])["eligible"] is True
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).json()[0]["required_skills"] == []

    replaced = client.post(route, headers=auth(client), json=body)
    assert replaced.status_code == 201
    approved = client.post(
        route + "/" + replaced.json()["id"] + "/approve",
        headers=auth(client, "wm-reviewer"), json=review,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["required_skills"][0]["skill_id"] == s["skill"]
    assert client.post(route, headers=auth(client), json=body).status_code == 409
    history = client.get(route)
    assert history.status_code == 200
    assert {p["status"] for p in history.json()} == {"rejected", "approved"}
    from app.equipment.models import AssetPolicyProposal
    rows = db.scalars(select(AssetPolicyProposal)).all()
    assert len(rows) == 2
    assert len({r.id for r in rows}) == 2
    from app.equipment.models import EquipmentAuditEvent
    actions = {r.action for r in db.scalars(select(EquipmentAuditEvent)).all()}
    assert {"policy.proposed", "policy.approved", "policy.rejected"} <= actions


def test_governed_pending_policy_does_not_hold_live_work_until_approval(
    scenario: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = scenario
    s = seed(client)
    verified_skills(client, s)
    verified_permit(client, s)
    asset = add_test_asset(client, s, "policy-live-22")
    work = create_work(client, s, "policy-live-work-22")
    link_test_asset(client, work, asset)
    assert assign(client, work, s["person"]).status_code == 200
    permit = prepare_test_permit(client, work)
    assert permit_transition(client, work, permit, "submit").status_code == 200
    assert permit_transition(
        client, work, permit, "approve", "wm-reviewer"
    ).status_code == 200
    start = datetime.fromisoformat(work["starts_at"])
    monkeypatch.setattr(work_service, "utcnow", lambda: start + timedelta(minutes=5))
    assert client.post(
        f"{BASE}/orders/{work['id']}/start", headers=auth(client),
    ).status_code == 200
    route = f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals"
    kind = post(
        client, f"/api/v1/credentials/enterprises/{s['enterprise']}/types", {
            "code": "governance-service-22", "name": "Synthetic service authorization",
            "kind": "training", "is_safety_critical": False,
            "requires_expiry": True,
        },
    )
    pending = client.post(route, headers=auth(client), json={
        "kind": "credential", "credential_type_id": kind["id"],
        "reason": "New machine maintenance qualification required by the plan",
    })
    assert pending.status_code == 201, pending.text
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "in_progress"
    assert client.post(
        f"{EQUIPMENT}/assets/{asset['id']}/required-credentials",
        headers=auth(client), json={"type_id": kind["id"]},
    ).status_code == 409
    approved = client.post(
        route + "/" + pending.json()["id"] + "/approve",
        headers=auth(client, "wm-reviewer"),
        json={"note": "Reviewed new service requirement and approved addition"},
    )
    assert approved.status_code == 200, approved.text
    assert kind["id"] in approved.json()["required_credential_type_ids"]
    assert client.get(f"{BASE}/orders/{work['id']}").json()["status"] == "on_hold"
    blocked = client.post(
        f"{BASE}/orders/{work['id']}/resume", headers=auth(client),
        json={"reason": "Permit for approved equipment requirement is missing"},
    )
    assert blocked.status_code == 409
    assert "EQUIPMENT_CREDENTIAL_MISSING" in str(blocked.json())


def test_governed_policy_invalid_payload_scope_and_stale_review(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    asset = add_test_asset(client, s, "policy-stale-22")
    route = f"{EQUIPMENT}/assets/{asset['id']}/policy-proposals"
    body = {
        "kind": "skill", "skill_id": s["skill"],
        "min_level_id": s["level_high"],
        "reason": "Competence threshold for synthetic repair authorization",
    }
    assert client.post(route, headers=auth(client), json={
        **body, "credential_type_id": s["permit"],
    }).status_code == 422
    assert client.post(route, headers=auth(client), json={
        **body, "min_level_id": s["foreign_person"],
    }).status_code == 422
    assert client.post(route, headers=auth(client), json={
        **body, "reason": "   ",
    }).status_code == 422
    assert client.post(route, headers=auth(client, "wm-manager"),
                       json=body).status_code == 403
    assert client.post(route, json=body).status_code == 403
    row = client.post(route, headers=auth(client), json=body).json()
    assert row["status"] == "pending"
    auth(client, "wm-viewer")
    assert client.get(route).status_code == 403
    auth(client)
    # A foreign asset cannot be approached through this tenant's policy path.
    assert client.get(
        f"{EQUIPMENT}/assets/{s['foreign_person']}/policy-proposals",
    ).status_code == 404
    import uuid
    assert client.post(
        route + f"/{uuid.uuid4()}/approve", headers=auth(client, "wm-reviewer"),
        json={"note": "Independent review of unknown policy proposal"},
    ).status_code == 404
    assert client.post(
        route + "/" + row["id"] + "/approve",
        headers=auth(client, "wm-reviewer"),
        json={"note": "    "},
    ).status_code == 422
    # Policy revalidated during independent review; deactivation denies approval.
    from app.competence.models import Skill
    skill = db.get(Skill, UUID(s["skill"]))
    skill.is_active = False
    db.commit()
    cannot = client.post(
        route + "/" + row["id"] + "/approve",
        headers=auth(client, "wm-reviewer"),
        json={"note": "Skill now inactive so approval must fail closed"},
    )
    assert cannot.status_code == 422
    assert client.get(route).json()[0]["status"] == "pending"
    assert client.get(
        f"{EQUIPMENT}/enterprises/{s['enterprise']}/assets",
    ).json()[0]["required_skills"] == []
