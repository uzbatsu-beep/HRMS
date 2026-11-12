"""Strict competence API contracts; published scales cannot be mutated."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Code = str
EvidenceKind = Literal["observation", "training", "document", "other"]


class CategoryCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None


class CategoryView(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID


class LevelCreate(BaseModel):
    ordinal: int = Field(ge=0, le=100)
    label: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ScaleCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    levels: list[LevelCreate] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def distinct_levels(self) -> "ScaleCreate":
        ordinals = [row.ordinal for row in self.levels]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("Scale level ordinals must be unique")
        return self


class LevelView(LevelCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scale_id: UUID


class ScaleView(BaseModel):
    id: UUID
    enterprise_id: UUID
    code: str
    name: str
    version: int
    levels: list[LevelView]


class SkillCreate(BaseModel):
    code: Code = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=160)
    category_id: UUID
    scale_id: UUID


class SkillView(SkillCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    is_active: bool


class LinkCreate(BaseModel):
    user_id: UUID
    person_id: UUID


class LinkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    person_id: UUID


class EvidenceCreate(BaseModel):
    kind: EvidenceKind
    description: str = Field(min_length=10, max_length=1500)
    reference: str | None = Field(default=None, max_length=250)


class EvidenceView(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID


class AssessmentCreate(BaseModel):
    skill_id: UUID
    level_id: UUID
    evidence: list[EvidenceCreate] = Field(default_factory=list, max_length=8)


class AssessmentView(BaseModel):
    id: UUID
    enterprise_id: UUID
    person_id: UUID
    skill_id: UUID
    scale_id: UUID
    level_id: UUID
    source: Literal["self", "expert"]
    status: Literal["pending", "approved", "rejected"]
    submitted_by: UUID
    submitted_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    evidence: list[EvidenceView]


class ReviewCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(min_length=10, max_length=1200)


class MatrixRow(BaseModel):
    person_id: UUID
    employee_code: str
    full_name: str
    skill_id: UUID
    skill_code: str
    skill_name: str
    level_id: UUID
    level_label: str
    level_ordinal: int
    reviewed_at: datetime


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enterprise_id: UUID
    actor_id: UUID
    action: str
    subject_id: UUID
    payload: str
    created_at: datetime
