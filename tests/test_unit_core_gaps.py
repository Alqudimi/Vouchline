"""Unit tests covering remaining core-logic branches.

Documents previously unexercised contracts in comparison, replay,
adapters, and capture without touching CLI behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vouchline.adapters.otlp_json import _attributes as _otel_attributes
from vouchline.capture import build_artifact, write_artifact
from vouchline.comparison import compare_artifacts
from vouchline.errors import InputError, ReplayError
from vouchline.models import InputEvent, Producer
from vouchline.replay import replay_artifact

PRODUCER = Producer(name="test", version="1")


def _event(
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


def _build(events: list[InputEvent], run_id: str = "run-1") -> object:
    return build_artifact(events, run_id=run_id, producer=PRODUCER, redaction_count=0)


def test_compare_detects_tool_change_across_events(tmp_path: Path) -> None:
    baseline = _build(
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ]
    )
    candidate = _build(
        [
            _event(1, "tool.requested", {"tool": "fetch"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ]
    )
    report = compare_artifacts(baseline, candidate)
    assert not report.passed
    codes = {finding.code for finding in report.findings}
    assert "TOOL_CHANGED" in codes
    assert report.findings[0].severity == "error"


def test_compare_detects_outcome_change_across_events(tmp_path: Path) -> None:
    baseline = _build(
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ]
    )
    candidate = _build(
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "timeout"}, "c1"),
        ]
    )
    report = compare_artifacts(baseline, candidate)
    assert not report.passed
    codes = {finding.code for finding in report.findings}
    assert "TOOL_OUTCOME_CHANGED" in codes


def test_compare_ignores_non_string_tool_and_status(tmp_path: Path) -> None:
    baseline = _build(
        [
            _event(1, "tool.requested", {"tool": 42}, "c1"),
            _event(2, "tool.responded", {"status": {"nested": True}}, "c1"),
        ]
    )
    candidate = _build(
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ]
    )
    report = compare_artifacts(baseline, candidate)
    codes = {finding.code for finding in report.findings}
    assert "TOOL_CHANGED" in codes


def test_compare_ignores_events_without_call_id(tmp_path: Path) -> None:
    baseline = _build([_event(1, "tool.requested", {"tool": "search"}, None)])
    candidate = _build([_event(1, "tool.requested", {"tool": "search"}, None)])
    report = compare_artifacts(baseline, candidate)
    assert report.passed


def test_replay_raises_on_reused_call_id_before_response(tmp_path: Path) -> None:
    artifact = _build(
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.requested", {"tool": "fetch"}, "c1"),
            _event(3, "tool.responded", {"status": "ok"}, "c1"),
        ]
    )
    with pytest.raises(ReplayError) as exc_info:
        replay_artifact(artifact)
    assert exc_info.value.details["call_id"] == "c1"


def test_otel_attributes_extracts_typed_values(tmp_path: Path) -> None:
    span = {
        "attributes": [
            {"key": "host", "value": {"stringValue": "example.com"}},
            {"key": "port", "value": {"intValue": 443}},
            {"key": "latency", "value": {"doubleValue": 0.5}},
            {"key": "ok", "value": {"boolValue": True}},
            {"key": "ignored", "value": "not-a-dict"},
        ]
    }
    values = _otel_attributes(span)
    assert values == {
        "host": "example.com",
        "port": 443,
        "latency": 0.5,
        "ok": True,
    }


def test_otel_attributes_ignores_invalid_items() -> None:
    span = {"attributes": [None, 42, {"key": 5}, {"key": "k", "value": []}]}
    values = _otel_attributes(span)
    assert values == {}


def test_write_artifact_unwritable_path(tmp_path: Path) -> None:
    artifact = _build([_event(1, "run.started", {})])
    # Pointing at a file path prevents the parent directory from being created.
    target = tmp_path / "existing-file"
    target.write_text("placeholder", encoding="utf-8")
    impossible = target / "artifact.json"
    with pytest.raises(InputError) as exc_info:
        write_artifact(impossible, artifact)
    assert exc_info.value.details["reason"] == "write_failed"


def test_build_artifact_requires_events() -> None:
    with pytest.raises(InputError):
        build_artifact([], run_id="run-1", producer=PRODUCER, redaction_count=0)
