"""Availability contracts: explicit offset datetimes, inclusive local weekdays."""

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator,
)


class ShiftRuleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    local_start: time
    local_end: time
    time_zone: str = Field(min_length=1, max_length=80)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> "ShiftRuleCreate":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("Shift end date precedes effective start")
        if self.local_start == self.local_end:
            raise ValueError("Shift must have nonzero local-time length")
        if self.local_start.tzinfo or self.local_end.tzinfo:
            raise ValueError("Shift time values must not include a timezone offset")
        return self

    @field_validator("time_zone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise ValueError("Use a valid IANA timezone name") from exc
        return value


class ShiftRuleView(ShiftRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    resource_id: UUID


class ClosureCreate(BaseModel):
    local_date: date
    time_zone: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=180)

    @field_validator("time_zone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise ValueError("Use a valid IANA timezone name") from exc
        return value


class ClosureView(ClosureCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID


class AbsenceCreate(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    category: Literal["leave", "training", "unavailable"]
    note: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def valid_range(self) -> "AbsenceCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("Absence must end after it starts")
        return self


class AbsenceView(BaseModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    category: str | None
    note: str | None
    cancelled_at: datetime | None


class ReservationCreate(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    external_reference: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_range(self) -> "ReservationCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("Reservation must end after it starts")
        return self


class ReservationView(BaseModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    external_reference: str | None
    cancelled_at: datetime | None


class Blocker(BaseModel):
    code: str
    message: str


class AvailabilityResult(BaseModel):
    resource_id: UUID
    starts_at: datetime
    ends_at: datetime
    available: bool
    blockers: list[Blocker]


class CalendarView(BaseModel):
    resource_id: UUID
    shift_rules: list[ShiftRuleView]
    absences: list[AbsenceView]
    reservations: list[ReservationView]
    closures: list[ClosureView]


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    actor_user_id: UUID
    action: str
    subject_id: UUID
    details_json: str
    created_at: datetime
