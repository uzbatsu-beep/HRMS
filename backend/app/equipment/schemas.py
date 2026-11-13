"""Read-only scope and constrained human-attestation API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
