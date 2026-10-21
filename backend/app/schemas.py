"""Shared API shapes. Business decisions remain in their owning services."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

Environment = Literal["development", "staging", "production"]
ENVIRONMENTS: tuple[Environment, ...] = ("development", "staging", "production")
FlagKey = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Description = Annotated[str, StringConstraints(strict=True, max_length=500)]


def validate_identifier(value: str) -> str:
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Whitespace padding and ASCII controls are not allowed")
    return value


GroupName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=64),
    AfterValidator(validate_identifier),
]
UserId = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128),
    AfterValidator(validate_identifier),
]


def unique_groups(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise ValueError("Group names must be unique")
    return value


Groups = Annotated[list[GroupName], Field(max_length=20), AfterValidator(unique_groups)]
Rollout = Annotated[StrictInt, Field(ge=0, le=100)]
Version = Annotated[StrictInt, Field(ge=1)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class FlagCreate(RequestModel):
    key: FlagKey
    description: Description = ""


class FlagUpdate(RequestModel):
    description: Description


class EnvironmentUpdate(RequestModel):
    enabled: StrictBool
    target_groups: Groups
    rollout_percentage: Rollout
    version: Version

    def sorted_target_groups(self) -> list[str]:
        return sorted(self.target_groups)


class EnvironmentResponse(ResponseModel):
    environment: Environment
    enabled: StrictBool
    target_groups: Groups
    rollout_percentage: Rollout
    version: Version
    updated_at: datetime


class FlagSummary(ResponseModel):
    id: UUID
    key: FlagKey
    description: Description
    archived: StrictBool
    created_at: datetime
    updated_at: datetime


class FlagDetail(FlagSummary):
    environments: list[EnvironmentResponse]


class FlagPage(ResponseModel):
    items: list[FlagSummary]
    total: int
    limit: int
    offset: int


class UserContext(RequestModel):
    id: UserId
    groups: Groups = Field(default_factory=list)


class EvaluationRequest(RequestModel):
    flag_key: FlagKey
    environment: Environment
    user: UserContext


class EvaluationResponse(ResponseModel):
    flag_key: FlagKey
    environment: Environment
    value: StrictBool
    reason: Literal["FLAG_DISABLED", "GROUP_MATCH", "ROLLOUT_INCLUDED", "ROLLOUT_EXCLUDED"]
    bucket: Annotated[StrictInt, Field(ge=0, le=9999)] | None


class AuditItem(ResponseModel):
    id: UUID
    flag_key: FlagKey
    environment: Environment | None
    action: Literal["FLAG_CREATED", "FLAG_UPDATED", "CONFIG_UPDATED", "FLAG_ARCHIVED"]
    actor: str
    before: dict | None
    after: dict
    created_at: datetime


class AuditPage(ResponseModel):
    items: list[AuditItem]
    total: int
    limit: int
    offset: int
