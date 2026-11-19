"""Validated, bounded declarative service-request workflows (non-safety only)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.configuration.schemas import CustomField

CODE = r"^[a-z][a-z0-9_]*$"


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=32, pattern=CODE)
    label: str = Field(min_length=1, max_length=80)
    terminal: bool = False


class WorkflowTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=32, pattern=CODE)
    label: str = Field(min_length=1, max_length=80)
    from_state: str
    to_state: str
    actor: Literal["creator", "manager", "admin"]
    independent_review: bool = False

    @model_validator(mode="after")
    def valid_transition(self) -> "WorkflowTransition":
        if self.from_state == self.to_state:
            raise ValueError("A transition must change state")
        if self.independent_review and self.actor == "creator":
            raise ValueError("Creator cannot independently review their own request")
        return self


class WorkflowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[CustomField] = Field(default_factory=list, max_length=12)
    states: list[WorkflowState] = Field(min_length=2, max_length=8)
    transitions: list[WorkflowTransition] = Field(min_length=1, max_length=24)
    initial_state: str

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDocument":
        fields = [field.code for field in self.fields]
        states = [state.code for state in self.states]
        transitions = [transition.code for transition in self.transitions]
        if len(fields) != len(set(fields)):
            raise ValueError("Duplicate form field codes")
        if len(states) != len(set(states)) or len(transitions) != len(set(transitions)):
            raise ValueError("Duplicate state/transition codes")
        lookup = {item.code: item for item in self.states}
        if self.initial_state not in lookup or lookup[self.initial_state].terminal:
            raise ValueError("Initial state must be a nonterminal state")
        if not any(item.terminal for item in self.states):
            raise ValueError("At least one terminal state is required")
        for transition in self.transitions:
            if transition.from_state not in lookup or transition.to_state not in lookup:
                raise ValueError("Every transition must reference defined states")
            if lookup[transition.from_state].terminal:
                raise ValueError("Terminal state cannot have outgoing transitions")
            if lookup[transition.to_state].terminal:
                if transition.actor == "creator" or not transition.independent_review:
                    raise ValueError("Terminal decisions require independent manager/admin")
        reachable = {self.initial_state}
        while True:
            next_reachable = reachable | {
                edge.to_state for edge in self.transitions if edge.from_state in reachable
            }
            if next_reachable == reachable:
                break
            reachable = next_reachable
        if set(states) != reachable:
            raise ValueError("Every state must be reachable from initial state")
        return self


class WorkflowDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=40, pattern=CODE)
    title: str = Field(min_length=2, max_length=100)
    document: WorkflowDocument

    @model_validator(mode="after")
    def only_service_metadata(self) -> "WorkflowDefinitionCreate":
        protected = ("permit", "work_order", "safety", "credential", "qualification",
                     "authorization", "access", "equipment")
        if any(self.code == s or self.code.startswith(s + "_") for s in protected):
            raise ValueError("Safety and access workflows cannot be redefined")
        return self


class WorkflowVersionView(WorkflowDefinitionCreate):
    id: UUID
    enterprise_id: UUID
    version: int
    status: Literal["draft", "validated", "approved", "published"]
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None = None
    published_by: UUID | None = None
    effective_on: date | None = None


class WorkflowPublish(BaseModel):
    effective_on: date = Field(default_factory=date.today)


class WorkflowCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_code: str = Field(min_length=2, max_length=40, pattern=CODE)
    unit_id: UUID
    title: str = Field(min_length=3, max_length=200)
    values: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def size(self) -> "WorkflowCaseCreate":
        if len(self.values) > 12:
            raise ValueError("Too many form values")
        return self


class WorkflowCaseView(BaseModel):
    id: UUID
    enterprise_id: UUID
    unit_id: UUID
    workflow_code: str
    workflow_version: int
    title: str
    state: str
    values: dict[str, str | int | bool]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_code: str = Field(min_length=2, max_length=32, pattern=CODE)
    expected_state: str = Field(min_length=2, max_length=32, pattern=CODE)
    note: str = Field(default="", max_length=400)


class WorkflowCaseEventView(BaseModel):
    id: UUID
    from_state: str | None
    to_state: str
    transition_code: str
    actor_id: UUID
    note: str
    created_at: datetime
