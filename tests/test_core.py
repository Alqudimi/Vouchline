from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest

from vouchline.capture import build_artifact, parse_jsonl
from vouchline.errors import InputError, IntegrityError, LimitError, ReplayError
from vouchline.integrity import verify_artifact
from vouchline.models import InputEvent, Policy, Producer
from vouchline.policy import evaluate_policy
from vouchline.replay import replay_artifact

PRODUCER = Producer(name="test", version="1")


def event(
    sequence: int,
    kind: str,
    payload: dict[str, object],
    call_id: str | None = None,
) -> InputEvent:
    return InputEvent(
        event_id=f"event-{sequence}",
        sequence=sequence,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        kind=kind,
        actor="test-agent",
        call_id=call_id,
        payload=payload,
    )


def artifact_with_tool(status: str = "ok"):
    events = [
        event(1, "run.started", {"task": "test"}),
        event(2, "tool.requested", {"tool": "search"}, "call-1"),
        event(3, "tool.responded", {"status": status}, "call-1"),
        event(4, "run.finished", {"status": "completed"}),
    ]
    return build_artifact(events, run_id="run-1", producer=PRODUCER, redaction_count=0)


def test_capture_redacts_and_verifies() -> None:
    stream = io.StringIO(
        json.dumps(
            {
                "schema_version": "v1",
                "event_id": "1",
                "sequence": 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "kind": "run.started",
                "actor": "agent",
                "payload": {"api_key": "never-persist-this"},
            }
        )
        + "\n"
    )
    events, count = parse_jsonl(stream)
    artifact = build_artifact(events, run_id="run", producer=PRODUCER, redaction_count=count)
    serialized = json.dumps(artifact.model_dump(mode="json"))
    assert "never-persist-this" not in serialized
    assert count == 1
    assert verify_artifact(artifact).valid


def test_hash_chain_detects_payload_tampering() -> None:
    artifact = artifact_with_tool()
    data = artifact.model_dump(mode="json")
    data["events"][1]["payload"]["tool"] = "tampered"
    tampered = artifact.__class__.model_validate(data)
    with pytest.raises(IntegrityError, match="digest"):
        verify_artifact(tampered)


def test_capture_rejects_non_contiguous_sequences() -> None:
    raw = {
        "schema_version": "v1",
        "event_id": "1",
        "sequence": 2,
        "timestamp": "2026-01-01T00:00:00Z",
        "kind": "run.started",
        "actor": "agent",
        "payload": {},
    }
    with pytest.raises(InputError, match="contiguous"):
        parse_jsonl(io.StringIO(json.dumps(raw) + "\n"))


def test_limits_are_enforced() -> None:
    with pytest.raises(LimitError):
        parse_jsonl(io.StringIO("{}\n"), max_bytes=2)


def test_replay_is_simulated_and_pairs_calls() -> None:
    report = replay_artifact(artifact_with_tool())
    assert report.passed is True
    assert report.simulated is True
    assert report.steps[0].tool == "search"
    assert report.steps[0].response_sequence == 3


def test_replay_rejects_missing_response() -> None:
    events = [
        event(1, "run.started", {}),
        event(2, "tool.requested", {"tool": "search"}, "missing"),
    ]
    artifact = build_artifact(events, run_id="run", producer=PRODUCER, redaction_count=0)
    report = replay_artifact(artifact)
    assert report.passed is False
    assert report.missing_responses == ["missing"]


def test_replay_rejects_unmatched_response() -> None:
    events = [
        event(1, "run.started", {}),
        event(2, "tool.responded", {"status": "ok"}, "orphan"),
    ]
    artifact = build_artifact(events, run_id="run", producer=PRODUCER, redaction_count=0)
    with pytest.raises(ReplayError, match="matching request"):
        replay_artifact(artifact)


def test_policy_passes_and_fails_deterministically() -> None:
    artifact = artifact_with_tool()
    passing = evaluate_policy(
        artifact,
        Policy(require_tools=["search"], max_tool_calls=1, deny_statuses=["error"]),
    )
    assert passing.passed is True
    failing = evaluate_policy(artifact, Policy(deny_tools=["search"]))
    assert failing.passed is False
    assert failing.findings[0].rule == "deny_tools"


def test_policy_denies_response_status() -> None:
    artifact = artifact_with_tool(status="timeout")
    report = evaluate_policy(artifact, Policy(deny_statuses=["timeout"]))
    assert report.passed is False
    assert report.findings[0].rule == "deny_statuses"
