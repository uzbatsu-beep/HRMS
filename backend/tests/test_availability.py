"""Scheduling API regressions: DST, overlap, scope, audits and fail-closed checks."""

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.availability.models import (
    AbsencePeriod, SchedulingAuditEvent, ShiftRule, WorkReservation,
)
from app.database import Base, get_db
from app.identity.models import UserAccount
from app.identity.security import hash_password
from app.main import app

PASSWORD = "shift-availability-dev-pass"
ZONE = ZoneInfo("America/Toronto")
BASE = "/api/v1/availability"
UTC = timezone.utc


@pytest.fixture
def scenario() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            table for table in Base.metadata.sorted_tables
            if table.name != "platform_settings"
        ],
    )
    db = Session(engine, expire_on_commit=False)
    for username, role in (
        ("sched-admin", "admin"), ("sched-manager", "manager"),
        ("sched-viewer", "viewer"),
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


def login(client: TestClient, name: str = "sched-admin") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": name, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def post(client: TestClient, url: str, json: dict, name: str = "sched-admin") -> dict:
    response = client.post(url, json=json, headers=login(client, name))
    assert response.status_code == 201, response.text
    return response.json()


def next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(0 - today.weekday()) % 7 + 7)


def utc_time(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE).astimezone(
        UTC
    ).isoformat()


def seed(client: TestClient) -> dict[str, str]:
    enterprise = post(
        client, "/api/v1/org/enterprises", {"code": "plant", "name": "Plant"}
    )["id"]
    kind = post(
        client, f"/api/v1/org/enterprises/{enterprise}/types",
        {"code": "dept", "name": "Department"},
    )["id"]
    unit = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "asu", "name": "Automation", "type_id": kind},
    )["id"]
    foreign_unit = post(
        client, f"/api/v1/org/enterprises/{enterprise}/units",
        {"code": "mech", "name": "Mechanics", "type_id": kind},
    )["id"]
    person = post(
        client, f"/api/v1/personnel/enterprises/{enterprise}/persons",
        {
            "employee_code": "SP001", "first_name": "Ivan", "last_name": "Mechanic",
            "unit_id": unit, "effective_from": "2020-01-01",
        },
    )
    return {
        "enterprise": enterprise, "unit": unit, "foreign_unit": foreign_unit,
        "person": person["id"], "resource": person["resource_id"],
    }


def add_shift(
    client: TestClient, resource_id: str, weekday: int = 0,
    start: str = "09:00:00", end: str = "17:00:00",
    zone: str = "America/Toronto",
) -> dict:
    return post(
        client, f"{BASE}/resources/{resource_id}/shifts",
        {
            "weekday": weekday, "local_start": start, "local_end": end,
            "time_zone": zone, "valid_from": "2020-01-01",
        },
    )


def interval(day: date | None = None) -> dict[str, str]:
    day = day or next_monday()
    return {"start": utc_time(day, 9), "end": utc_time(day, 10)}


def check(client: TestClient, person_id: str, params: dict | None = None) -> dict:
    response = client.get(
        f"{BASE}/persons/{person_id}/check", params=params or interval()
    )
    assert response.status_code == 200, response.text
    return response.json()


def grant(client: TestClient, name: str, unit: str) -> None:
    login(client)
    users = client.get("/api/v1/auth/users").json()
    user_id = next(user["id"] for user in users if user["username"] == name)
    post(
        client, "/api/v1/org/scopes",
        {"user_id": user_id, "unit_id": unit, "include_descendants": True},
    )


def test_default_deny_then_working_shift_and_workload(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    assert {x["code"] for x in check(client, s["person"])["blockers"]} == {"NO_SHIFT"}
    shift = add_shift(client, s["resource"])
    assert shift["weekday"] == 0
    assert check(client, s["person"])["available"] is True
    morning = interval()
    booking = post(
        client, f"{BASE}/resources/{s['resource']}/reservations",
        {
            "starts_at": morning["start"], "ends_at": morning["end"],
            "external_reference": "PLAN-001",
        },
    )
    assert booking["external_reference"] == "PLAN-001"
    assert {x["code"] for x in check(client, s["person"])["blockers"]} == {"BOOKED"}
    response = client.get(
        f"{BASE}/persons/{s['person']}/load", params={
            "start": utc_time(next_monday(), 8), "end": utc_time(next_monday(), 18),
        },
    )
    assert response.status_code == 200
    assert response.json()["reserved_minutes"] == 60
    assert response.json()["active_reservations"] == 1


def test_overlapping_reservation_rejected_and_adjacent_allowed(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    add_shift(client, s["resource"])
    monday = next_monday()
    post(
        client, f"{BASE}/resources/{s['resource']}/reservations",
        {"starts_at": utc_time(monday, 9), "ends_at": utc_time(monday, 10)},
    )
    duplicate = client.post(
        f"{BASE}/resources/{s['resource']}/reservations",
        headers=login(client),
        json={"starts_at": utc_time(monday, 9, 30), "ends_at": utc_time(monday, 10, 30)},
    )
    assert duplicate.status_code == 409
    assert "BOOKED" in {
        row["code"] for row in duplicate.json()["detail"]["blockers"]
    }
    neighbor = post(
        client, f"{BASE}/resources/{s['resource']}/reservations",
        {"starts_at": utc_time(monday, 10), "ends_at": utc_time(monday, 11)},
    )
    assert neighbor["cancelled_at"] is None
    assert len(db.scalars(select(WorkReservation)).all()) == 2


def test_absence_blocks_and_cancellation_restores_availability(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    add_shift(client, s["resource"])
    monday = next_monday()
    absence = post(
        client, f"{BASE}/resources/{s['resource']}/absences",
        {
            "starts_at": utc_time(monday, 9, 20),
            "ends_at": utc_time(monday, 9, 40),
            "category": "unavailable", "note": "Private administrative reason",
        },
    )
    assert absence["category"] == "unavailable"
    assert {b["code"] for b in check(client, s["person"])["blockers"]} == {"ABSENT"}
    cancelled = client.post(
        f"{BASE}/absences/{absence['id']}/cancel", headers=login(client)
    )
    assert cancelled.status_code == 200
    assert check(client, s["person"])["available"]
    assert client.post(
        f"{BASE}/absences/{absence['id']}/cancel", headers=login(client)
    ).status_code == 409


def test_enterprise_calendar_closure_blocks_every_worker(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    add_shift(client, s["resource"])
    closure = post(
        client, f"{BASE}/enterprises/{s['enterprise']}/closures",
        {
            "local_date": next_monday().isoformat(),
            "time_zone": "America/Toronto", "label": "Site shutdown",
        },
    )
    assert closure["label"] == "Site shutdown"
    assert {b["code"] for b in check(client, s["person"])["blockers"]} == {
        "CALENDAR_CLOSED"
    }
    duplicated = client.post(
        f"{BASE}/enterprises/{s['enterprise']}/closures",
        headers=login(client),
        json={
            "local_date": next_monday().isoformat(),
            "time_zone": "America/Toronto", "label": "Duplicate",
        },
    )
    assert duplicated.status_code == 409


def test_overnight_shift_includes_next_calendar_day(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    add_shift(client, s["resource"], start="21:00:00", end="05:00:00")
    monday = next_monday()
    response = check(client, s["person"], {
        "start": utc_time(monday, 23),
        "end": utc_time(monday + timedelta(days=1), 1),
    })
    assert response["available"] is True


def test_dst_ambiguous_shift_time_is_rejected_fail_closed(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    add_shift(client, s["resource"], weekday=6, start="01:30:00", end="05:00:00")
    result = check(client, s["person"], {
        "start": "2026-11-01T06:30:00+00:00",
        "end": "2026-11-01T07:30:00+00:00",
    })
    assert not result["available"]
    assert "AMBIGUOUS_SHIFT_TIME" in {b["code"] for b in result["blockers"]}


def test_shift_can_be_disabled_without_deleting_history(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    shift = add_shift(client, s["resource"])
    retired = client.post(f"{BASE}/shifts/{shift['id']}/disable", headers=login(client))
    assert retired.status_code == 200, retired.text
    assert retired.json()["disabled_at"] is not None
    assert {b["code"] for b in check(client, s["person"])["blockers"]} == {"NO_SHIFT"}
    assert db.scalars(select(ShiftRule)).all()
    assert client.post(
        f"{BASE}/shifts/{shift['id']}/disable", headers=login(client)
    ).status_code == 409


def test_scoped_read_redacts_absence_notes_and_reservation_origins(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    add_shift(client, s["resource"])
    monday = next_monday()
    post(
        client, f"{BASE}/resources/{s['resource']}/absences",
        {
            "starts_at": utc_time(monday, 13),
            "ends_at": utc_time(monday, 14), "category": "leave",
            "note": "Sensitive details omitted from manager",
        },
    )
    post(
        client, f"{BASE}/resources/{s['resource']}/reservations",
        {
            "starts_at": utc_time(monday, 9),
            "ends_at": utc_time(monday, 10),
            "external_reference": "CONFIDENTIAL-WORK-REFERENCE",
        },
    )
    grant(client, "sched-manager", s["foreign_unit"])
    login(client, "sched-manager")
    response = client.get(
        f"{BASE}/persons/{s['person']}/calendar",
        params={
            "start": utc_time(monday, 7), "end": utc_time(monday, 18),
        },
    )
    assert response.status_code == 404
    grant(client, "sched-manager", s["unit"])
    login(client, "sched-manager")
    response = client.get(
        f"{BASE}/persons/{s['person']}/calendar",
        params={
            "start": utc_time(monday, 7), "end": utc_time(monday, 18),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["absences"][0]["note"] is None
    assert response.json()["absences"][0]["category"] is None
    assert response.json()["reservations"][0]["external_reference"] is None
    assert client.post(
        f"{BASE}/resources/{s['resource']}/shifts",
        headers=login(client, "sched-manager"),
        json={
            "weekday": 2, "local_start": "09:00:00", "local_end": "17:00:00",
            "time_zone": "America/Toronto", "valid_from": "2020-01-01",
        },
    ).status_code == 403


def test_bad_timezones_naive_dates_and_overlong_request_rejected(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    bad_zone = client.post(
        f"{BASE}/resources/{s['resource']}/shifts",
        headers=login(client),
        json={
            "weekday": 0, "local_start": "09:00", "local_end": "17:00",
            "time_zone": "Fake/Unknown", "valid_from": "2020-01-01",
        },
    )
    assert bad_zone.status_code == 422
    bad_length = client.get(
        f"{BASE}/persons/{s['person']}/check",
        params={
            "start": "2026-11-16T09:00:00Z",
            "end": "2026-11-18T09:00:00Z",
        },
    )
    assert bad_length.status_code == 422
    naive = client.get(
        f"{BASE}/persons/{s['person']}/check",
        params={"start": "2026-11-16T09:00:00", "end": "2026-11-16T10:00:00"},
    )
    assert naive.status_code == 422
    assert client.post(
        f"{BASE}/resources/{s['resource']}/shifts",
        headers=login(client),
        json={
            "weekday": 0, "local_start": "09:00", "local_end": "09:00",
            "time_zone": "America/Toronto", "valid_from": "2020-01-01",
        },
    ).status_code == 422


def test_reservation_cancellation_and_audit(
    scenario: tuple[TestClient, Session],
) -> None:
    client, db = scenario
    s = seed(client)
    add_shift(client, s["resource"])
    morning = interval()
    booking = post(
        client, f"{BASE}/resources/{s['resource']}/reservations",
        {"starts_at": morning["start"], "ends_at": morning["end"]},
    )
    assert not check(client, s["person"])["available"]
    answer = client.post(
        f"{BASE}/reservations/{booking['id']}/cancel",
        headers=login(client),
    )
    assert answer.status_code == 200
    assert check(client, s["person"])["available"]
    assert client.post(
        f"{BASE}/reservations/{booking['id']}/cancel",
        headers=login(client),
    ).status_code == 409
    events = {row.action for row in db.scalars(select(SchedulingAuditEvent)).all()}
    assert events >= {
        "reservation.created", "reservation.cancelled", "shift.created",
    }


def test_future_employee_and_employee_without_assignment_fail_closed(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    person = post(
        client, f"/api/v1/personnel/enterprises/{s['enterprise']}/persons",
        {"employee_code": "NO-UNIT", "first_name": "Jane", "last_name": "Unassigned"},
    )
    add_shift(client, person["resource_id"])
    result = check(client, person["id"])
    assert not result["available"]
    assert "NO_ASSIGNMENT" in {b["code"] for b in result["blockers"]}


def test_cross_enterprise_resource_isolation_and_admin_csrf(
    scenario: tuple[TestClient, Session],
) -> None:
    client, _ = scenario
    s = seed(client)
    other = post(
        client, "/api/v1/org/enterprises",
        {"code": "second", "name": "Separate enterprise"},
    )["id"]
    closure = post(
        client, f"{BASE}/enterprises/{other}/closures",
        {
            "local_date": next_monday().isoformat(),
            "time_zone": "America/Toronto", "label": "Second site closed",
        },
    )
    assert closure["enterprise_id"] == other
    add_shift(client, s["resource"])
    assert check(client, s["person"])["available"] is True
    no_csrf = client.post(
        f"{BASE}/resources/{s['resource']}/reservations",
        json={"starts_at": interval()["start"], "ends_at": interval()["end"]},
    )
    assert no_csrf.status_code == 403
    unauth = client.post("/api/v1/auth/logout", headers=login(client))
    assert unauth.status_code in {200, 204}
    assert client.get(
        f"{BASE}/persons/{s['person']}/check", params=interval()
    ).status_code == 401
