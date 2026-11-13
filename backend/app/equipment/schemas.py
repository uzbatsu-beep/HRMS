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
    version: int


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


class CrewReadinessSnapshot(BaseModel):
    """Redacted, on-demand result of mandatory crew/work gates, not authorization."""

    work_order_id: UUID
    work_status: str
    checked_at: datetime
    last_persisted_safety_check_at: datetime | None
    leader_assigned: bool
    members_checked: int
    members_blocked: int
    equipment_blocker_codes: list[str]
    crew_blocker_codes: list[str]
    gates_passed: bool
    crew_eligibility_checked: Literal[True] = True
    read_only: Literal[True] = True


class EquipmentAuditRow(BaseModel):
    """Bounded audit metadata only, never arbitrary detail payloads."""

    id: UUID
    action: str
    actor_id: UUID
    actor_username: str
    subject_id: UUID
    created_at: datetime


class EquipmentAuditPage(BaseModel):
    enterprise_id: UUID
    items: list[EquipmentAuditRow]
    next_cursor: str | None
    has_more: bool
    detail_payloads_included: Literal[False] = False


class PolicyProposalCreate(BaseModel):
    kind: Literal["credential", "skill", "skill_upgrade"]
    credential_type_id: UUID | None = None
    skill_id: UUID | None = None
    min_level_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("A substantive policy proposal reason is required")
        return value

    @model_validator(mode="after")
    def validate_policy_kind(self) -> "PolicyProposalCreate":
        if self.kind == "credential":
            if (self.credential_type_id is None or self.skill_id or self.min_level_id
                    or self.expected_version is not None):
                raise ValueError("Credential proposals require only credential_type_id")
        elif self.skill_id is None or self.min_level_id is None or self.credential_type_id:
            raise ValueError("Skill proposals require skill_id and min_level_id")
        elif self.kind == "skill_upgrade" and self.expected_version is None:
            raise ValueError("Upgrades require expected_version")
        elif self.kind == "skill" and self.expected_version is not None:
            raise ValueError("New skills must not carry expected_version")
        return self


class PolicyReview(BaseModel):
    note: str = Field(min_length=10, max_length=400)

    @field_validator("note")
    @classmethod
    def substantive_note(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Review note requires ten non-whitespace characters")
        return value


class PolicyProposalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    asset_id: UUID
    kind: Literal["credential", "skill"]
    credential_type_id: UUID | None
    skill_id: UUID | None
    scale_id: UUID | None
    min_level_id: UUID | None
    expected_version: int | None
    reason: str
    status: Literal["pending", "approved", "rejected"]
    proposed_by: UUID
    proposed_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None



class SkillPolicyRevisionView(BaseModel):
    requirement_id: UUID
    skill_id: UUID
    version: int
    min_level_id: UUID
    min_ordinal: int
    approved_by: UUID
    approved_at: datetime
    proposal_id: UUID | None
