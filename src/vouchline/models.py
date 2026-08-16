"""Typed domain contracts for Vouchline artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CoreEventKind = Literal[
    "run.started",
    "tool.requested",
    "tool.responded",
    "policy.decision",
    "run.finished",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Producer(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)


class InputEvent(StrictModel):
    schema_version: Literal["v1"] = "v1"
    event_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    timestamp: datetime
    kind: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=200)
    call_id: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        allowed = {
            "run.started",
            "tool.requested",
            "tool.responded",
            "policy.decision",
            "run.finished",
        }
        if value not in allowed and not value.startswith("extension."):
            raise ValueError("kind must be a core event or extension.*")
        return value


class EvidenceEvent(InputEvent):
    previous_hash: str = Field(min_length=64, max_length=64)
    event_hash: str = Field(min_length=64, max_length=64)


class RedactionSummary(StrictModel):
    profile: str = Field(min_length=1, max_length=100)
    redacted_fields: int = Field(ge=0)


class Manifest(StrictModel):
    event_count: int = Field(ge=0)
    first_hash: str = Field(min_length=64, max_length=64)
    last_hash: str = Field(min_length=64, max_length=64)
    artifact_sha256: str = Field(min_length=64, max_length=64)


class Artifact(StrictModel):
    schema_version: Literal["v1"] = "v1"
    artifact_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    producer: Producer
    created_at: datetime
    redaction: RedactionSummary
    events: list[EvidenceEvent] = Field(min_length=1)
    manifest: Manifest


class Policy(StrictModel):
    deny_tools: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = Field(default=None, ge=0)
    require_tools: list[str] = Field(default_factory=list)
    deny_statuses: list[str] = Field(default_factory=list)


class PolicyFinding(StrictModel):
    rule: str
    message: str
    sequence: int | None = None
    call_id: str | None = None


class PolicyReport(StrictModel):
    passed: bool
    findings: list[PolicyFinding] = Field(default_factory=list)
    tool_call_count: int = Field(ge=0)


class ReplayStep(StrictModel):
    sequence: int
    call_id: str
    tool: str
    status: str
    simulated: bool = True
    response_sequence: int | None = None


class ReplayReport(StrictModel):
    passed: bool
    simulated: bool = True
    steps: list[ReplayStep] = Field(default_factory=list)
    missing_responses: list[str] = Field(default_factory=list)


class ComparisonFinding(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    severity: Literal["info", "warning", "error"]
    call_id: str | None = None


class ComparisonReport(StrictModel):
    passed: bool
    baseline_artifact_id: str
    candidate_artifact_id: str
    findings: list[ComparisonFinding] = Field(default_factory=list)


class VerificationReport(StrictModel):
    valid: bool
    event_count: int
    first_hash: str
    last_hash: str
    artifact_sha256: str
