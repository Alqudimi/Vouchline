from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vouchline.adapters import messages_to_events
from vouchline.errors import InputError


def test_mcp_tool_call_and_result_become_paired_events() -> None:
    events = messages_to_events(
        [
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"q": "vouchline"}},
                "timestamp": "2026-08-18T00:00:00+00:00",
            },
            {
                "jsonrpc": "2.0",
                "id": 7,
                "result": {"content": [{"type": "text", "text": "ok"}]},
                "timestamp": "2026-08-18T00:00:01+00:00",
            },
        ]
    )
    assert [event["kind"] for event in events] == ["tool.requested", "tool.responded"]
    assert events[0]["call_id"] == "7"
    assert events[0]["payload"]["tool"] == "search"
    assert events[1]["payload"]["status"] == "ok"


def test_mcp_error_response_and_notification_are_normalized() -> None:
    events = messages_to_events(
        [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": "x",
                "error": {"code": -32603, "message": "tool failed"},
            },
        ]
    )
    assert events[0]["kind"] == "extension.mcp.message"
    assert events[0]["payload"]["method"] == "notifications/initialized"
    assert events[1]["kind"] == "tool.responded"
    assert events[1]["payload"]["status"] == "error"


def test_mcp_invalid_ids_are_preserved_as_extensions() -> None:
    events = messages_to_events([{"id": True, "result": {"ok": True}}])
    assert events[0]["kind"] == "extension.mcp.message"
    assert events[0]["payload"]["has_result"] is True


def test_mcp_timestamp_fallback_is_valid_utc_and_bound_is_enforced() -> None:
    before = datetime.now(UTC)
    events = messages_to_events([{"method": "ping"}])
    after = datetime.now(UTC)
    timestamp = datetime.fromisoformat(events[0]["timestamp"])
    assert before <= timestamp <= after
    with pytest.raises(InputError):
        messages_to_events([], max_messages=0)


def test_normalize_mcp_cli_writes_events_and_machine_output(tmp_path) -> None:
    from typer.testing import CliRunner

    from vouchline.cli import app

    source = tmp_path / "transcript.jsonl"
    output = tmp_path / "events.jsonl"
    source.write_text(
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search"}}\n'
        '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        ["normalize-mcp", str(source), "--output", str(output), "--json"],
    )
    assert result.exit_code == 0, result.output
    assert '"event_count": 2' in result.output
    assert output.read_text(encoding="utf-8").count("\n") == 2


def test_normalize_mcp_cli_rejects_invalid_json(tmp_path) -> None:
    from typer.testing import CliRunner

    from vouchline.cli import app

    source = tmp_path / "invalid.jsonl"
    output = tmp_path / "events.jsonl"
    source.write_text("not-json\n", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["normalize-mcp", str(source), "--output", str(output), "--json"],
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output
