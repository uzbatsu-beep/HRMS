"""Read-only scope and constrained human-attestation API contracts."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

AssetKind = Literal["machine", "robot", "production_line", "other"]
AssetStatus = Literal["active", "out_of_service"]
PermitStatus = Literal["draft", "submitted", "approved", "revoked"]


class AssetCreate(BaseModel):
    unit_id: UUID
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=2, max_length=180)
    kind: AssetKind
    serial_number: str | None = Field(default=None, max_length=120)


class AssetStateChange(BaseModel):
    status: AssetStatus
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("A substantive reason is required")
        return value


class AssetSkillCreate(BaseModel):
    skill_id: UUID
    min_level_id: UUID


class AssetSkillView(BaseModel):
    id: UUID
    skill_id: UUID
    skill_code: str
    skill_name: str
    min_level_id: UUID
    min_ordinal: int


class AssetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    unit_id: UUID
    code: str
    name: str
    kind: AssetKind
    serial_number: str | None
    status: AssetStatus
    required_credential_type_ids: list[UUID]
    required_skills: list[AssetSkillView]


class AssetCredentialCreate(BaseModel):
    type_id: UUID


class EquipmentLinkCreate(BaseModel):
    asset_id: UUID


class PermitDraft(BaseModel):
    hazards_reviewed: bool
    energy_isolation_attested: bool
    area_access_attested: bool
    evidence_reference: str = Field(min_length=10, max_length=200)

    @field_validator("evidence_reference")
    @classmethod
    def reference(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Document/evidence reference must be meaningful")
        return value


class PermitReason(BaseModel):
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("A substantive reason is required")
        return value


class PermitView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    work_order_id: UUID
    version: int
    status: PermitStatus
    hazards_reviewed: bool
    energy_isolation_attested: bool
    area_access_attested: bool
    evidence_reference: str | None
    prepared_by: UUID
    created_at: datetime
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    revoked_by: UUID | None
    revoked_at: datetime | None
    revoke_reason: str | None


class SafetyPackage(BaseModel):
    work_order_id: UUID
    asset: AssetView | None
    permit: PermitView | None
    equipment_blockers: list[str]


class LinkedWorkReadiness(BaseModel):
    work_order_id: UUID
    work_code: str
    title: str
    unit_id: UUID
    asset_id: UUID
    asset_code: str
    status: str
    permit_version: int | None
    permit_status: str | None
    software_blockers: list[str]
    crew_eligibility_checked: bool = False


class EquipmentReadiness(BaseModel):
    enterprise_id: UUID
    unit_id: UUID | None
    total: int
    blocked: int
    on_hold: int
    items: list[LinkedWorkReadiness]


class DowntimeCreate(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def trimmed_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("At least ten nonspace characters required")
        return value

    @model_validator(mode="after")
    def bounded_interval(self) -> "DowntimeCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("Downtime end must follow start")
        if self.ends_at - self.starts_at > timedelta(days=14):
            raise ValueError("A downtime window may not exceed 14 days")
        return self


class DowntimeCancel(BaseModel):
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def trimmed_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("At least ten nonspace characters required")
        return value


class DowntimeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    asset_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by: UUID
    created_at: datetime
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
