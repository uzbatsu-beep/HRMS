"""Validated API contracts for configurable organization hierarchies."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnterpriseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)


class EnterpriseView(EnterpriseCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class UnitTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=120)


class UnitTypeView(UnitTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID


class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    type_id: UUID
    parent_id: UUID | None = None


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type_id: UUID | None = None
    parent_id: UUID | None = None


class UnitView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    parent_id: UUID | None
    type_id: UUID
    code: str
    name: str


class ScopeGrantCreate(BaseModel):
    user_id: UUID
    unit_id: UUID
    include_descendants: bool = True


class ScopeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    unit_id: UUID
    include_descendants: bool


class AuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    actor_user_id: UUID
    action: str
    subject_id: UUID
    details_json: str


class PermissionGrantCreate(BaseModel):
    user_id: UUID
    unit_id: UUID
    code: Literal[
        "equipment.policy.read",
        "equipment.policy.propose",
        "equipment.policy.review",
        "competence.assessment.review",
        "credentials.record.review",
        "work.order.create",
        "work.order.assign",
        "work.crew.manage",
        "work.order.priority",
        "work.order.start",
        "work.order.complete",
        "work.order.cancel",
        "work.order.revalidate",
        "work.order.hold",
        "work.order.resume",
    ]


class PermissionGrantView(PermissionGrantCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    granted_by: UUID
    created_at: datetime


class PermissionTemplateApply(BaseModel):
    user_id: UUID
    unit_id: UUID
    template: Literal["work.planner", "work.dispatcher", "work.supervisor", "work.coordinator"]


class PermissionTemplateView(BaseModel):
    code: str
    label: str
    permissions: list[str]


class PermissionTemplateApplyResult(PermissionTemplateApply):
    granted_codes: list[str]
