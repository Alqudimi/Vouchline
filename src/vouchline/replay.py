"""Side-effect-free replay of recorded tool results."""

from __future__ import annotations

from .errors import ReplayError
from .integrity import verify_artifact
from .models import Artifact, ReplayReport, ReplayStep


def _required_text(payload: dict[str, object], key: str, sequence: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ReplayError(
            "tool event is missing a valid field",
            details={"sequence": sequence, "field": key},
        )
    return value


def replay_artifact(artifact: Artifact) -> ReplayReport:
    """Reconstruct the recorded tool path without executing anything."""
    verify_artifact(artifact)
    pending: dict[str, ReplayStep] = {}
    steps: list[ReplayStep] = []
    missing: list[str] = []

    for event in artifact.events:
        if event.kind == "tool.requested":
            if not event.call_id:
                raise ReplayError(
                    "tool request has no call_id",
                    details={"sequence": event.sequence},
                )
            if event.call_id in pending:
                raise ReplayError(
                    "tool call_id is reused before a response",
                    details={"sequence": event.sequence, "call_id": event.call_id},
                )
            tool = _required_text(event.payload, "tool", event.sequence)
            step = ReplayStep(
                sequence=event.sequence,
                call_id=event.call_id,
                tool=tool,
                status="pending",
            )
            pending[event.call_id] = step
            continue

        if event.kind != "tool.responded":
            continue
        if not event.call_id:
            raise ReplayError(
                "tool response has no call_id",
                details={"sequence": event.sequence},
            )
        original = pending.pop(event.call_id, None)
        if original is None:
            raise ReplayError(
                "tool response has no matching request",
                details={"sequence": event.sequence, "call_id": event.call_id},
            )
        status = _required_text(event.payload, "status", event.sequence)
        steps.append(
            ReplayStep(
                sequence=original.sequence,
                call_id=original.call_id,
                tool=original.tool,
                status=status,
                response_sequence=event.sequence,
            )
        )

    if pending:
        missing = sorted(pending)
    return ReplayReport(passed=not missing, steps=steps, missing_responses=missing)
