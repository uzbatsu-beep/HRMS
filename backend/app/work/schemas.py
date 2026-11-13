"""Work order API: immutable requested skills and explainable safety decisions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class RequiredSkillCreate(BaseModel):
    skill_id: UUID
    min_level_id: UUID


class RequiredSkillView(RequiredSkillCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scale_id: UUID
    min_ordinal: int
    skill_name: str


class WorkCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    unit_id: UUID
    activity_code: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    required_skills: list[RequiredSkillCreate] = Field(min_length=1, max_length=20)
    priority: Literal["routine", "normal", "urgent", "critical"] = "normal"

    @model_validator(mode="after")
    def unique_requirements(self) -> "WorkCreate":
        ids = [row.skill_id for row in self.required_skills]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate required skills are not allowed")
        if not self.title.strip():
            raise ValueError("Work title cannot be blank")
        if self.ends_at <= self.starts_at:
            raise ValueError("Work end must follow start")
        return self


class AssignmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    person_id: UUID
    resource_id: UUID
    reservation_id: UUID
    assigned_at: datetime


class CrewCreate(BaseModel):
    person_id: UUID
    role: Literal["specialist", "assistant", "observer"]


class LeadReplacement(BaseModel):
    person_id: UUID
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Replacement justification needs at least 10 characters")
        return value


class CrewMemberView(BaseModel):
    id: UUID
    person_id: UUID
    resource_id: UUID
    reservation_id: UUID
    role: Literal["specialist", "assistant", "observer"]
    joined_at: datetime
    removed_at: datetime | None


class WorkView(BaseModel):
    id: UUID
    enterprise_id: UUID
    unit_id: UUID
    code: str
    title: str
    description: str | None
    activity_code: str
    starts_at: datetime
    ends_at: datetime
    status: Literal["open", "assigned", "in_progress", "on_hold", "completed", "cancelled"]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    required_skills: list[RequiredSkillView]
    assignment: AssignmentView | None
    priority: Literal["routine", "normal", "urgent", "critical"]
    crew: list[CrewMemberView]
    on_hold_at: datetime | None
    hold_reason: str | None
    last_safety_check_at: datetime | None


class Blocker(BaseModel):
    source: Literal["person", "organization", "skill", "credential", "calendar"]
    code: str
    message: str


class CandidateView(BaseModel):
    person_id: UUID
    employee_code: str
    full_name: str
    resource_id: UUID | None
    eligible: bool
    blockers: list[Blocker]
    verified_skills: list[UUID]
    verified_credentials: list[UUID]


class AssignmentCreate(BaseModel):
    person_id: UUID


class AssignmentDecision(BaseModel):
    eligible: bool
    candidate: CandidateView


class SafetyMember(BaseModel):
    role: Literal["lead", "specialist", "assistant", "observer"]
    person_id: UUID
    reservation_valid: bool
    candidate: CandidateView


class SafetyCheck(BaseModel):
    work_order_id: UUID
    checked_at: datetime
    status: str
    passed: bool
    members: list[SafetyMember]


class PriorityChange(BaseModel):
    priority: Literal["routine", "normal", "urgent", "critical"]
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Priority change requires a reason of 10 or more characters")
        return value


class ReasonNote(BaseModel):
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        note = value.strip()
        if len(note) < 10:
            raise ValueError("Reason must contain at least 10 non-whitespace characters")
        return note


class WorkAuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    actor_user_id: UUID
    work_order_id: UUID
    action: str
    details_json: str
    created_at: datetime
