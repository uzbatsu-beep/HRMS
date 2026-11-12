"""Credential API contracts with strict dates and independent reviews."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Code = str
CredentialKind = Literal["permit", "certificate", "qualification", "training"]


class CredentialTypeCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=180)
    kind: CredentialKind
    is_safety_critical: bool = False
    requires_expiry: bool = True

    @model_validator(mode="after")
    def ensure_safety_expiration(self) -> "CredentialTypeCreate":
        if self.is_safety_critical and not self.requires_expiry:
            raise ValueError("Safety critical credentials require an expiry date")
        return self


class CredentialTypeView(CredentialTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID


class CredentialCreate(BaseModel):
    person_id: UUID
    type_id: UUID
    document_reference: str = Field(min_length=1, max_length=180)
    issuer: str = Field(min_length=1, max_length=180)
    issued_on: date
    valid_from: date
    expires_on: date | None = None

    @model_validator(mode="after")
    def check_dates(self) -> "CredentialCreate":
        if self.valid_from < self.issued_on:
            raise ValueError("Validity cannot precede issuance")
        if self.expires_on is not None and self.expires_on < self.valid_from:
            raise ValueError("Expiration cannot precede validity start")
        return self


class CredentialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    person_id: UUID
    type_id: UUID
    document_reference: str
    issuer: str
    issued_on: date
    valid_from: date
    expires_on: date | None
    status: Literal["pending", "verified", "rejected", "revoked"]
    submitted_by: UUID
    submitted_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    revoked_by: UUID | None
    revoked_at: datetime | None
    revoke_reason: str | None


class CredentialReview(BaseModel):
    decision: Literal["verified", "rejected"]
    note: str = Field(min_length=10, max_length=1200)

    @field_validator("note")
    @classmethod
    def substantive_note(cls, value: str) -> str:
        note = value.strip()
        if len(note) < 10:
            raise ValueError("Review justification requires 10 non-whitespace characters")
        return note


class CredentialRevoke(BaseModel):
    reason: str = Field(min_length=10, max_length=1200)

    @field_validator("reason")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        reason = value.strip()
        if len(reason) < 10:
            raise ValueError("Revocation reason requires 10 non-whitespace characters")
        return reason


class RequirementCreate(BaseModel):
    activity_code: Code = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    type_id: UUID


class RequirementView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    activity_code: str
    type_id: UUID


class EligibilityBlocker(BaseModel):
    code: str
    type_id: UUID | None
    message: str


class EligibilityCheck(BaseModel):
    type_id: UUID
    credential_id: UUID
    expires_on: date | None


class EligibilityResult(BaseModel):
    person_id: UUID
    enterprise_id: UUID
    activity_code: str
    checked_on: date
    eligible: bool
    blockers: list[EligibilityBlocker]
    valid_credentials: list[EligibilityCheck]


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    actor_id: UUID
    action: str
    subject_id: UUID
    details_json: str
    created_at: datetime
