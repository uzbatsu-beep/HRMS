"""Public identity API contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


UserRole = Literal["admin", "manager", "viewer"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: UserRole = "viewer"


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: UserRole
    is_active: bool


class LoginResult(BaseModel):
    user: UserView
    csrf_token: str


class SessionResult(LoginResult):
    pass
