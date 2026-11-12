"""Type-safe contracts for human profiles and assignment histories."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PersonCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    unit_id: UUID | None = None
    position_title: str | None = Field(default=None, max_length=160)
    effective_from: date = Field(default_factory=date.today)


class PersonUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)


class PersonView(BaseModel):
    id: UUID
    resource_id: UUID
    enterprise_id: UUID
    employee_code: str
    first_name: str
    last_name: str
    middle_name: str | None
    archived_at: datetime | None
    current_unit_id: UUID | None
    current_unit_name: str | None
    position_title: str | None
    current_since: date | None


class AssignmentCreate(BaseModel):
    unit_id: UUID
    effective_from: date = Field(default_factory=date.today)
    effective_to: date | None = None
    position_title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def valid_period(self) -> "AssignmentCreate":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class TransferCreate(BaseModel):
    unit_id: UUID
    effective_on: date = Field(default_factory=date.today)
    position_title: str | None = Field(default=None, max_length=160)


class AssignmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_id: UUID
    unit_id: UUID
    position_title: str | None
    effective_from: date
    effective_to: date | None


class TeamMembershipCreate(BaseModel):
    unit_id: UUID
    effective_from: date = Field(default_factory=date.today)
    effective_to: date | None = None

    @model_validator(mode="after")
    def valid_period(self) -> "TeamMembershipCreate":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class TeamMembershipView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_id: UUID
    unit_id: UUID
    effective_from: date
    effective_to: date | None


class MembershipClose(BaseModel):
    effective_to: date


class PersonDetail(PersonView):
    assignments: list[AssignmentView]
    team_memberships: list[TeamMembershipView]


class PersonnelAuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    person_id: UUID
    actor_user_id: UUID
    action: str
    details_json: str
    created_at: datetime
