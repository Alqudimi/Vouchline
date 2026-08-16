"""Hash-chain construction and artifact verification."""

from __future__ import annotations

from .canonical import artifact_digest, event_digest
from .errors import IntegrityError
from .models import Artifact, EvidenceEvent, InputEvent, VerificationReport

ZERO_HASH = "0" * 64


def hash_events(events: list[InputEvent]) -> list[EvidenceEvent]:
    """Add a linked SHA-256 digest to each already-sanitized event."""
    previous = ZERO_HASH
    hashed: list[EvidenceEvent] = []
    for event in events:
        base = event.model_dump(mode="json")
        digest = event_digest(base, previous)
        hashed_event = EvidenceEvent(
            **base,
            previous_hash=previous,
            event_hash=digest,
        )
        hashed.append(hashed_event)
        previous = digest
    return hashed


def verify_artifact(artifact: Artifact) -> VerificationReport:
    previous = ZERO_HASH
    for expected_sequence, event in enumerate(artifact.events, start=1):
        if event.sequence != expected_sequence:
            raise IntegrityError(
                "event sequence is not contiguous",
                details={"expected": expected_sequence, "actual": event.sequence},
            )
        if event.previous_hash != previous:
            raise IntegrityError(
                "event hash chain is broken",
                details={"sequence": event.sequence, "reason": "previous_hash_mismatch"},
            )
        base = event.model_dump(mode="json")
        actual_hash = base.pop("event_hash")
        declared_previous = base.pop("previous_hash")
        expected_hash = event_digest(base, declared_previous)
        if actual_hash != expected_hash:
            raise IntegrityError(
                "event digest does not match its content",
                details={"sequence": event.sequence, "reason": "event_hash_mismatch"},
            )
        previous = actual_hash

    if artifact.manifest.event_count != len(artifact.events):
        raise IntegrityError(
            "manifest event count does not match artifact",
            details={"manifest": artifact.manifest.event_count, "actual": len(artifact.events)},
        )
    if artifact.manifest.first_hash != artifact.events[0].event_hash:
        raise IntegrityError("manifest first_hash does not match the first event")
    if artifact.manifest.last_hash != artifact.events[-1].event_hash:
        raise IntegrityError("manifest last_hash does not match the last event")

    actual_artifact_hash = artifact_digest(artifact.model_dump(mode="json"))
    if artifact.manifest.artifact_sha256 != actual_artifact_hash:
        raise IntegrityError(
            "artifact digest does not match its content",
            details={"reason": "artifact_hash_mismatch"},
        )
    return VerificationReport(
        valid=True,
        event_count=len(artifact.events),
        first_hash=artifact.events[0].event_hash,
        last_hash=artifact.events[-1].event_hash,
        artifact_sha256=actual_artifact_hash,
    )
