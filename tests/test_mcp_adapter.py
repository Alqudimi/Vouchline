"""Tests for the MCP/JSONL normalization adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vouchline.adapters import mcp_lines_to_events
from vouchline.errors import InputError

FIXTURES = Path(__file__).parent / "fixtures"


def _rows(*lines: str) -> list[dict]:
    return [json.loads(line) for line in lines]


def test_mcp_tool_call_becomes_request_and_response() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": '
        '{"tool": "search", "callId": "c1", "arguments": {"q": "mcp"}}}',
        '{"method": "notifications/tools/call_result", "params": '
        '{"tool": "search", "callId": "c1", "status": "ok"}}',
    )
    events, metadata = mcp_lines_to_events(rows)
    assert [event["kind"] for event in events] == ["tool.requested", "tool.responded"]
    assert events[0]["payload"]["tool"] == "search"
    assert events[0]["payload"]["arguments"] == {"q": "mcp"}
    assert events[0]["call_id"] == "c1"
    assert events[1]["payload"]["status"] == "ok"
    assert metadata["source_format"] == "mcp-jsonl-v1"
    assert metadata["rows_processed"] == 2
    assert not metadata["truncated"]


def test_mcp_error_result_is_preserved() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": {"tool": "edit", "callId": "c2"}}',
        '{"method": "notifications/tools/call_result", "params": '
        '{"tool": "edit", "callId": "c2", "status": "error", '
        '"error": {"code": -1, "message": "read-only file"}}}',
    )
    events, _ = mcp_lines_to_events(rows)
    assert events[1]["kind"] == "tool.responded"
    assert events[1]["payload"]["status"] == "error"
    assert events[1]["payload"]["error"]["message"] == "read-only file"


def test_mcp_unknown_notification_is_preserved_as_extension() -> None:
    rows = _rows(
        '{"method": "notifications/resources/list", "params": {"callId": "r1"}}',
    )
    events, _ = mcp_lines_to_events(rows)
    assert events[0]["kind"] == "extension.mcp.notification"
    assert events[0]["payload"]["method"] == "notifications/resources/list"


def test_mcp_timeout_is_recorded_in_payload() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": '
        '{"tool": "fetch", "callId": "c3", "timeout": 60}}',
    )
    events, _ = mcp_lines_to_events(rows)
    assert events[0]["payload"]["timeout"] == 60


def test_mcp_custom_timestamp_is_used() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": '
        '{"tool": "fetch", "callId": "c4"}, "timestamp": "2026-08-18T10:00:00Z"}',
    )
    events, _ = mcp_lines_to_events(rows)
    assert events[0]["timestamp"].startswith("2026-08-18")


def test_mcp_result_without_tool_is_rejected() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call_result", "params": {"callId": "c5"}}',
    )
    with pytest.raises(InputError) as exc_info:
        mcp_lines_to_events(rows)
    assert exc_info.value.details["reason"] == "missing_result_fields"


def test_mcp_call_without_call_id_is_rejected() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": {"tool": "search"}}',
    )
    with pytest.raises(InputError) as exc_info:
        mcp_lines_to_events(rows)
    assert exc_info.value.details["reason"] == "missing_call_fields"


def test_mcp_row_without_method_is_rejected() -> None:
    rows = _rows('{"params": {"tool": "search", "callId": "c6"}}')
    with pytest.raises(InputError) as exc_info:
        mcp_lines_to_events(rows)
    assert exc_info.value.details["reason"] == "missing_method"


def test_mcp_unknown_method_is_rejected() -> None:
    rows = _rows('{"method": "notifications/unknown/things"}')
    with pytest.raises(InputError) as exc_info:
        mcp_lines_to_events(rows)
    assert exc_info.value.details["reason"] == "unknown_method"


def test_mcp_non_object_record_is_rejected() -> None:
    with pytest.raises(InputError) as exc_info:
        mcp_lines_to_events([["not", "an", "object"]])  # type: ignore[list-item]
    assert exc_info.value.details["reason"] == "record_not_object"


def test_mcp_bounded_max_rows_is_enforced() -> None:
    rows = [
        json.loads(
            f'{{"method": "notifications/tools/call", "params": {{"tool": "t", "callId": "{n}"}}}}'
        )
        for n in range(5)
    ]
    events, metadata = mcp_lines_to_events(rows, max_rows=2)
    assert metadata["rows_processed"] == 2
    assert metadata["truncated"]
    assert len(events) == 2


def test_mcp_zero_max_rows_is_rejected() -> None:
    with pytest.raises(InputError):
        mcp_lines_to_events([], max_rows=0)


def test_mcp_empty_stream_is_empty() -> None:
    events, metadata = mcp_lines_to_events([])
    assert events == []
    assert metadata["rows_processed"] == 0


def test_mcp_sequences_are_contiguous_across_methods() -> None:
    rows = _rows(
        '{"method": "notifications/tools/call", "params": {"tool": "a", "callId": "c1"}}',
        '{"method": "notifications/tools/call_result", "params": {"tool": "a", "callId": "c1"}}',
        '{"method": "notifications/resources/list", "params": {}}',
    )
    events, _ = mcp_lines_to_events(rows)
    assert [event["sequence"] for event in events] == [1, 2, 3]


def test_mcp_fixture_file_loads_offline() -> None:
    """The shipped fixture proves the adapter works without any network access."""
    rows = [
        json.loads(line)
        for line in (FIXTURES / "mcp_sample.jsonl").read_text().splitlines()
        if line.strip()
    ]
    events, metadata = mcp_lines_to_events(rows)
    assert len(events) == 5
    assert metadata["rows_processed"] == 5
    assert events[0]["call_id"] == "c1"
