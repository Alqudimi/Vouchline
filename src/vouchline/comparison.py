"""Deterministic comparison of verified evidence artifacts."""

from __future__ import annotations

from typing import Literal

from .errors import InputError
from .integrity import verify_artifact
from .models import Artifact, ComparisonFinding, ComparisonReport


def _tool_outcomes(artifact: Artifact) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for event in artifact.events:
        if event.kind != "tool.responded" or not event.call_id:
            continue
        status = event.payload.get("status")
        if isinstance(status, str):
            outcomes[event.call_id] = status
    return outcomes


def _tool_names(artifact: Artifact) -> dict[str, str]:
    names: dict[str, str] = {}
    for event in artifact.events:
        if event.kind != "tool.requested" or not event.call_id:
            continue
        tool = event.payload.get("tool")
        if isinstance(tool, str):
            names[event.call_id] = tool
    return names


def compare_artifacts(baseline: Artifact, candidate: Artifact) -> ComparisonReport:
    """Compare two verified artifacts without executing either run."""
    verify_artifact(baseline)
    verify_artifact(candidate)
    if baseline.artifact_id == candidate.artifact_id:
        raise InputError(
            "baseline and candidate must be different artifacts",
            details={"artifact_id": baseline.artifact_id},
        )

    findings: list[ComparisonFinding] = []
    baseline_names = _tool_names(baseline)
    candidate_names = _tool_names(candidate)
    baseline_statuses = _tool_outcomes(baseline)
    candidate_statuses = _tool_outcomes(candidate)

    if len(candidate.events) != len(baseline.events):
        findings.append(
            ComparisonFinding(
                code="EVENT_COUNT_CHANGED",
                message=(
                    f"event count changed from {len(baseline.events)} to {len(candidate.events)}"
                ),
                severity="warning",
            )
        )

    for call_id in sorted(set(baseline_names) | set(candidate_names)):
        before = baseline_names.get(call_id)
        after = candidate_names.get(call_id)
        if before != after:
            findings.append(
                ComparisonFinding(
                    code="TOOL_CHANGED",
                    message=f"tool for {call_id} changed from {before!r} to {after!r}",
                    severity="error",
                    call_id=call_id,
                )
            )
        before_status = baseline_statuses.get(call_id)
        after_status = candidate_statuses.get(call_id)
        if before_status != after_status:
            severity: Literal["warning", "error"] = (
                "error" if after_status in {"error", "timeout", "denied"} else "warning"
            )
            findings.append(
                ComparisonFinding(
                    code="TOOL_OUTCOME_CHANGED",
                    message=(
                        f"outcome for {call_id} changed from {before_status!r} to {after_status!r}"
                    ),
                    severity=severity,
                    call_id=call_id,
                )
            )

    baseline_finished = [e for e in baseline.events if e.kind == "run.finished"]
    candidate_finished = [e for e in candidate.events if e.kind == "run.finished"]
    baseline_status = baseline_finished[-1].payload.get("status") if baseline_finished else None
    candidate_status = candidate_finished[-1].payload.get("status") if candidate_finished else None
    if baseline_status != candidate_status:
        findings.append(
            ComparisonFinding(
                code="RUN_STATUS_CHANGED",
                message=f"run status changed from {baseline_status!r} to {candidate_status!r}",
                severity="error" if candidate_status in {"error", "failed"} else "warning",
            )
        )

    return ComparisonReport(
        passed=not any(f.severity == "error" for f in findings),
        baseline_artifact_id=baseline.artifact_id,
        candidate_artifact_id=candidate.artifact_id,
        findings=findings,
    )
