"""Capture JSONL events into portable evidence artifacts."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from .canonical import artifact_digest, canonical_bytes
from .errors import InputError, LimitError
from .integrity import hash_events
from .models import Artifact, InputEvent, Manifest, Producer, RedactionSummary
from .redaction import redact

DEFAULT_MAX_EVENTS = 100_000
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


def parse_jsonl(
    stream: TextIO,
    *,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[list[InputEvent], int]:
    events: list[InputEvent] = []
    redaction_count = 0
    consumed = 0
    for line_number, line in enumerate(stream, start=1):
        consumed += len(line.encode("utf-8"))
        if consumed > max_bytes:
            raise LimitError("input exceeds the configured byte limit")
        if not line.strip():
            continue
        if len(events) >= max_events:
            raise LimitError("input exceeds the configured event limit")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(
                "input contains invalid JSON",
                details={"line": line_number, "reason": "json_decode_error"},
            ) from exc
        if not isinstance(raw, dict):
            raise InputError(
                "each JSONL record must be an object",
                details={"line": line_number, "reason": "record_not_object"},
            )
        sanitized = redact(raw)
        redaction_count += sanitized.count
        try:
            event = InputEvent.model_validate(sanitized.value)
        except ValueError as exc:
            raise InputError(
                "input contains an invalid event",
                details={"line": line_number, "reason": "event_schema_error"},
            ) from exc
        expected_sequence = len(events) + 1
        if event.sequence != expected_sequence:
            raise InputError(
                "event sequences must start at 1 and be contiguous",
                details={"line": line_number, "expected": expected_sequence},
            )
        events.append(event)
    if not events:
        raise InputError("input contains no events", details={"reason": "empty_stream"})
    return events, redaction_count


def build_artifact(
    events: list[InputEvent],
    *,
    run_id: str,
    producer: Producer,
    redaction_count: int,
    artifact_id: str | None = None,
    created_at: datetime | None = None,
) -> Artifact:
    if not events:
        raise InputError("cannot build an artifact without events")
    hashed_events = hash_events(events)
    manifest = Manifest(
        event_count=len(hashed_events),
        first_hash=hashed_events[0].event_hash,
        last_hash=hashed_events[-1].event_hash,
        artifact_sha256="0" * 64,
    )
    draft = Artifact(
        artifact_id=artifact_id or str(uuid.uuid4()),
        run_id=run_id,
        producer=producer,
        created_at=created_at or datetime.now(UTC),
        redaction=RedactionSummary(profile="default", redacted_fields=redaction_count),
        events=hashed_events,
        manifest=manifest,
    )
    digest = artifact_digest(draft.model_dump(mode="json"))
    return Artifact(
        **draft.model_dump(exclude={"manifest"}),
        manifest=Manifest(
            event_count=manifest.event_count,
            first_hash=manifest.first_hash,
            last_hash=manifest.last_hash,
            artifact_sha256=digest,
        ),
    )


def load_artifact(path: Path) -> Artifact:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(
            "artifact file could not be read as JSON",
            details={"path": str(path), "reason": "invalid_json_or_io"},
        ) from exc
    try:
        return Artifact.model_validate(raw)
    except ValueError as exc:
        raise InputError(
            "artifact does not match the Vouchline schema",
            details={"path": str(path), "reason": "artifact_schema_error"},
        ) from exc


def write_artifact(path: Path, artifact: Artifact) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(artifact.model_dump(mode="json")) + b"\n")
    except OSError as exc:
        raise InputError(
            "artifact could not be written",
            details={"path": str(path), "reason": "write_failed"},
        ) from exc
