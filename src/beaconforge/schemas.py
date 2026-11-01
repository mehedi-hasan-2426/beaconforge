from datetime import UTC, date, datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Commit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    authored_at: AwareDatetime


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["deployment", "incident", "restoration"]
    external_id: str = Field(min_length=1, max_length=160, pattern=r"^[\w./:-]+$")
    occurred_at: AwareDatetime
    environment: str = Field(default="production", min_length=1, max_length=64)
    outcome: Literal["success", "failure"] = "success"
    commit_scope: Literal["complete", "head_only", "unknown"] = "unknown"
    commits: list[Commit] = Field(default_factory=list, max_length=200)
    deployment_id: str | None = Field(default=None, min_length=1, max_length=160)
    incident_id: str | None = Field(default=None, min_length=1, max_length=160)
    restored_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_attribution(self) -> Self:
        if self.occurred_at > datetime.now(UTC):
            raise ValueError("event timestamp is in the future")
        if any(commit.authored_at > self.occurred_at for commit in self.commits):
            raise ValueError("commit timestamp follows deployment")
        if len({commit.sha for commit in self.commits}) != len(self.commits):
            raise ValueError("commit hashes must be unique")
        if self.kind == "incident" and not self.deployment_id:
            raise ValueError("incident must reference its causing deployment")
        if self.kind == "restoration" and (
            not self.incident_id or self.deployment_id or self.restored_at or self.commits
        ):
            raise ValueError("restoration must reference an incident without other event fields")
        if self.kind != "restoration" and self.incident_id:
            raise ValueError("only restoration events reference incident_id")
        if self.kind == "deployment" and (self.deployment_id or self.restored_at):
            raise ValueError("deployment cannot contain incident fields")
        if self.kind == "incident" and self.commits:
            raise ValueError("incident cannot contain commits")
        if self.restored_at and (
            self.restored_at < self.occurred_at or self.restored_at > datetime.now(UTC)
        ):
            raise ValueError("restoration must follow incident start and not be in the future")
        return self


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment_start: date
    deployment_end: date
    incident_start: date | None = None
    incident_end: date | None = None

    @model_validator(mode="after")
    def validate_intervals(self) -> Self:
        if self.deployment_end <= self.deployment_start:
            raise ValueError("deployment coverage end must follow start")
        if (self.incident_start is None) != (self.incident_end is None):
            raise ValueError("incident coverage needs both dates or neither")
        if self.incident_start and self.incident_end and self.incident_end <= self.incident_start:
            raise ValueError("incident coverage end must follow start")
        return self
