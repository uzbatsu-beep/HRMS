"""Strict declarative form schema; never evaluates user-supplied expressions."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CustomField(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["text", "integer", "boolean", "choice"]
    required: bool = False
    max_length: int | None = Field(default=None, ge=1, le=400)
    min_value: int | None = Field(default=None, ge=-1000000, le=1000000)
    max_value: int | None = Field(default=None, ge=-1000000, le=1000000)
    options: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def check_rules(self) -> "CustomField":
        protected = (
            "role", "permit", "credential", "safety", "authorization",
            "eligible", "work_status", "unit_id", "enterprise_id",
        )
        if any(self.code == p or self.code.startswith(p + "_") for p in protected):
            raise ValueError("Reserved safety/identity identifiers cannot be configured")
        if self.kind == "choice":
            if len(self.options) < 2 or len(set(self.options)) != len(self.options):
                raise ValueError("Choice needs at least two unique entries")
            if any(not x.strip() or len(x) > 80 for x in self.options):
                raise ValueError("Choice entries must be 1..80 characters")
        elif self.options:
            raise ValueError("Options are only supported for choice fields")
        if self.kind != "text" and self.max_length is not None:
            raise ValueError("max_length applies only to text")
        if self.kind != "integer" and (
            self.min_value is not None or self.max_value is not None
        ):
            raise ValueError("min/max values apply only to integer")
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("min_value must not exceed max_value")
        return self


class ConfigDocument(BaseModel):
    fields: list[CustomField] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def unique_codes(self) -> "ConfigDocument":
        codes = [field.code for field in self.fields]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate custom field codes")
        return self


class ConfigCreate(BaseModel):
    document: ConfigDocument


class ConfigView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    version: int
    status: Literal["draft", "validated", "approved", "published"]
    document: ConfigDocument
    created_by: UUID
    created_at: datetime
    validated_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    published_by: UUID | None
    published_at: datetime | None
    effective_on: date | None


class PublishRequest(BaseModel):
    effective_on: date = Field(default_factory=date.today)


class PersonFieldsInput(BaseModel):
    values: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bound(self) -> "PersonFieldsInput":
        if len(self.values) > 24:
            raise ValueError("Too many submitted fields")
        return self


class PersonFieldsView(BaseModel):
    person_id: UUID
    config_version: int | None
    fields: list[CustomField]
    values: dict[str, str | int | bool | None]
