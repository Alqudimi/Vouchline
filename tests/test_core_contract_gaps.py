"""Tests closing core library contract gaps: artifact write failures,
canonical serialization of date/time values, self-comparison rejection,
replay call-id contract, and adapter defensive branches.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from tests.test_cli_contract_gaps import _build_events, _write_artifact
from typer.testing import CliRunner

from vouchline.adapters import spans_to_events
from vouchline.adapters.mcp_jsonl import messages_to_events
from vouchline.canonical import jsonable
from vouchline.capture import build_artifact, write_artifact
from vouchline.cli import app
from vouchline.comparison import compare_artifacts
from vouchline.errors import InputError, ReplayError
from vouchline.models import InputEvent, Producer
from vouchline.replay import replay_artifact
from vouchline.reporting import comparison_junit

runner = CliRunner()


def _base_event(sequence: int, kind: str, payload: dict, call_id: str | None = None):
    return InputEvent(
        schema_version="v1",
        event_id=f"evt-{sequence}",
        sequence=sequence,
        timestamp=_dt.datetime(2026, 8, 1, tzinfo=_dt.UTC),
        kind=kind,
        actor="agent",
        call_id=call_id,
        payload=payload,
    )


def _artifact(events: list[InputEvent]) -> object:
    return build_artifact(
        events, run_id="gap", producer=Producer(name="p", version="1"), redaction_count=0
    )


# ---------------------------------------------------------------------------
# write_artifact: directory creation and write failure
# ---------------------------------------------------------------------------


def test_write_artifact_creates_parent_directories(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "artifact.json"
    write_artifact(nested, _artifact([_base_event(1, "run.started", {"task": "x"})]))
    assert nested.exists()


def test_write_artifact_oserror_wraps_input_error(tmp_path: Path) -> None:
    with (
        mock.patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")),
        pytest.raises(InputError) as exc_info,
    ):
        write_artifact(
            tmp_path / "out.json", _artifact([_base_event(1, "run.started", {"task": "x"})])
        )
    assert exc_info.value.details["reason"] == "write_failed"


# ---------------------------------------------------------------------------
# canonical: jsonable for datetimes and dates
# ---------------------------------------------------------------------------


def test_jsonable_serializes_datetime_and_date_isoformat() -> None:
    assert jsonable(_dt.datetime(2026, 8, 1, 12, 0, tzinfo=_dt.UTC)) == "2026-08-01T12:00:00+00:00"
    assert jsonable(_dt.date(2026, 8, 1)) == "2026-08-01"
    assert jsonable("plain") == "plain"


# ---------------------------------------------------------------------------
# comparison: self-comparison is rejected with a typed error
# ---------------------------------------------------------------------------


def test_compare_artifacts_self_pair_raises_typed_error() -> None:
    events = [
        _base_event(1, "run.started", {"task": "x"}),
        _base_event(2, "tool.requested", {"tool": "t"}, "c-1"),
        _base_event(3, "tool.responded", {"status": "ok"}, "c-1"),
        _base_event(4, "run.finished", {"status": "completed"}),
    ]
    artifact = _artifact(events)
    with pytest.raises(InputError) as exc_info:
        compare_artifacts(artifact, artifact)
    assert exc_info.value.code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# replay: call-id reuse before response is rejected
# ---------------------------------------------------------------------------


def test_replay_rejects_reused_call_id_before_response() -> None:
    events = [
        _base_event(1, "run.started", {"task": "x"}),
        _base_event(2, "tool.requested", {"tool": "t"}, "c-1"),
        _base_event(3, "tool.requested", {"tool": "t"}, "c-1"),
    ]
    with pytest.raises(ReplayError) as exc_info:
        replay_artifact(_artifact(events))
    assert exc_info.value.details["call_id"] == "c-1"


def test_replay_request_missing_call_id_is_rejected() -> None:
    events = [
        _base_event(1, "run.started", {"task": "x"}),
        _base_event(2, "tool.requested", {"tool": "t"}, call_id=None),
    ]
    with pytest.raises(ReplayError):
        replay_artifact(_artifact(events))


# ---------------------------------------------------------------------------
# adapters: defensive branches for malformed records
# ---------------------------------------------------------------------------


def test_mcp_adapter_unknown_tool_for_non_dict_params() -> None:
    events = messages_to_events([{"jsonrpc": "2.0", "id": 1, "method": "tools/call"}])
    assert any(
        event.get("kind") == "tool.requested" and event.get("payload", {}).get("tool") == "unknown"
        for event in events
    )


def _otlp_envelope(span: dict[str, object]) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {"spans": [span]},
                ],
            },
        ],
    }


def test_otlp_adapter_skips_non_dict_attribute_items() -> None:
    span = {
        "traceId": "a" * 32,
        "spanId": "b" * 16,
        "name": "tool.called",
        "attributes": ["not-a-dict", {"key": "tool_name", "value": {"stringValue": "t"}}],
    }
    rows = spans_to_events(_otlp_envelope(span))
    assert rows


def test_otlp_adapter_skips_attributes_without_string_values() -> None:
    span = {
        "traceId": "a" * 32,
        "spanId": "b" * 16,
        "name": "tool.called",
        "attributes": [{"key": "tool_name", "value": {}}],
    }
    rows = spans_to_events(_otlp_envelope(span))
    assert rows


# ---------------------------------------------------------------------------
# reporting: junit severity attribute for non-error findings
# ---------------------------------------------------------------------------


def test_junit_non_error_finding_uses_status_attribute() -> None:
    from vouchline.models import ComparisonFinding, ComparisonReport

    report = ComparisonReport(
        passed=False,
        baseline_artifact_id="a",
        candidate_artifact_id="b",
        findings=[ComparisonFinding(code="EVENT_COUNT_CHANGED", message="m", severity="warning")],
    )
    rendered = comparison_junit(report)
    assert 'status="warning"' in rendered


def test_junit_error_finding_emits_failure_element() -> None:
    from vouchline.models import ComparisonFinding, ComparisonReport

    report = ComparisonReport(
        passed=False,
        baseline_artifact_id="a",
        candidate_artifact_id="b",
        findings=[ComparisonFinding(code="TOOL_STATUS_CHANGED", message="boom", severity="error")],
    )
    rendered = comparison_junit(report)
    assert "<failure" in rendered and "boom" in rendered


# ---------------------------------------------------------------------------
# remaining small gaps: human CLI output paths and adapter variants
# ---------------------------------------------------------------------------


def test_mcp_adapter_unknown_tool_for_empty_dict_params() -> None:
    events = messages_to_events(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}},
        ]
    )
    assert any(
        event.get("kind") == "tool.requested" and event.get("payload", {}).get("tool") == "unknown"
        for event in events
    )


def test_otlp_adapter_honors_int_value_attribute() -> None:
    span = {
        "traceId": "a" * 32,
        "spanId": "b" * 16,
        "name": "tool.called",
        "attributes": [
            {"key": "tool_name", "value": {"stringValue": "t"}},
            {"key": "call_count", "value": {"intValue": 7}},
        ],
    }
    rows = spans_to_events(_otlp_envelope(span))
    assert rows


def test_cli_compare_human_failed_output(tmp_path: Path) -> None:
    a, b = _two_artifacts_local(tmp_path)
    different = build_artifact(
        _events_local()
        + [
            InputEvent(
                schema_version="v1",
                event_id="extra",
                sequence=5,
                timestamp=_dt.datetime(2026, 8, 1, tzinfo=_dt.UTC),
                kind="run.finished",
                actor="agent",
                call_id=None,
                payload={"status": "failed"},
            ),
        ],
        run_id="alt",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    b.write_text(json.dumps(different.model_dump(mode="json")) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["compare", str(a), str(b)])
    assert result.exit_code == 4, result.output
    assert "Comparison failed" in result.output


def test_cli_replay_human_success_output(tmp_path: Path) -> None:
    artifact = _write_artifact_gap(tmp_path / "a.json")  # noqa: F401
    result = runner.invoke(app, ["replay", str(artifact)])
    assert result.exit_code == 0, result.output
    assert "Replay verified" in result.output


def _events_local() -> list[InputEvent]:
    return _build_events()


def _two_artifacts_local(tmp_path: Path):
    return _write_artifact(tmp_path / "baseline.json"), _write_artifact(tmp_path / "candidate.json")


def _write_artifact_gap(path: Path) -> Path:
    artifact = build_artifact(
        _events_local(),
        run_id="gap",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    path.write_bytes(json.dumps(artifact.model_dump(mode="json")).encode() + b"\n")
    return path
