"""Pure MCP JSONL normalization into Vouchline input events.

The adapter only transforms supplied Python data. It never opens a socket,
imports an SDK, or executes a provider-specific action.

Expected input rows are MCP JSON-RPC notifications and results captured as
one JSON object per line. See ``tests/fixtures/mcp_sample.jsonl`` for
examples. Known tool call methods map to ``tool.requested`` and ``tool.responded``;
unknown notifications are preserved as ``extension.mcp.notification`` events
so nothing silently disappears. Source identifiers and format version are
kept in the payload and producer metadata as required by the contribution
guidelines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..errors import InputError

METHODS = {
    "notifications/tools/call": "tool.requested",
    "notifications/tools/call_result": "tool.responded",
    "notifications/prompts/prompt": "extension.mcp.prompt",
    "notifications/prompts/list": "extension.mcp.prompt_list",
    "notifications/resources/list": "extension.mcp.resource_list",
}

MCP_FORMAT_VERSION = "mcp-jsonl-v1"


def _timestamp(row: dict[str, Any]) -> str:
    """Use the row timestamp when present; otherwise fall back to now in UTC."""
    raw = row.get("timestamp") or row.get("params", {}).get("timestamp")
    if isinstance(raw, str):
        try:
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return stamp.isoformat()
        except ValueError:
            pass
    return datetime.now(UTC).isoformat()


def _request_event(
    sequence: int,
    tool: str,
    call_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    params = row.get("params", {}) or {}
    arguments = params.get("arguments", {})
    payload: dict[str, Any] = {
        "tool": str(tool),
        "source": "mcp",
    }
    if isinstance(arguments, dict):
        payload["arguments"] = dict(arguments)
    if params.get("timeout"):
        payload["timeout"] = params["timeout"]
    return {
        "event_id": str(call_id) + ":request",
        "sequence": sequence,
        "timestamp": _timestamp(row),
        "kind": "tool.requested",
        "actor": "mcp",
        "call_id": str(call_id),
        "payload": payload,
    }


def _responded_event(
    sequence: int,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    params = row.get("params", {}) or {}
    tool = params.get("tool")
    call_id = params.get("callId")
    if not isinstance(tool, str) or not isinstance(call_id, str):
        return None
    status = params.get("status", "ok")
    payload: dict[str, Any] = {
        "tool": str(tool),
        "status": str(status),
        "source": "mcp",
    }
    if isinstance(params.get("output"), dict):
        payload["output"] = dict(params["output"])
    if isinstance(params.get("error"), dict):
        payload["error"] = dict(params["error"])
    return {
        "event_id": str(call_id) + ":response",
        "sequence": sequence,
        "timestamp": _timestamp(row),
        "kind": "tool.responded",
        "actor": "mcp",
        "call_id": str(call_id),
        "payload": payload,
    }


def _extension_event(
    sequence: int,
    method: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    params = row.get("params", {}) or {}
    return {
        "event_id": f"{method}:{sequence}",
        "sequence": sequence,
        "timestamp": _timestamp(row),
        "kind": "extension.mcp.notification",
        "actor": "mcp",
        "call_id": str(params.get("callId")) if isinstance(params.get("callId"), str) else None,
        "payload": {"method": method, "params_keys": sorted(params.keys())},
    }


def _row_to_events(sequence: int, row: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return (events, sequences_consumed) for a single validated row."""
    method = row.get("method")
    if not isinstance(method, str):
        raise InputError(
            "MCP JSONL row is missing a method string",
            details={"reason": "missing_method"},
        )

    if method == "notifications/tools/call":
        params = row.get("params", {}) or {}
        tool = params.get("tool")
        call_id = params.get("callId")
        if not isinstance(tool, str) or not isinstance(call_id, str):
            raise InputError(
                "tools/call row requires string params.tool and params.callId",
                details={"method": method, "reason": "missing_call_fields"},
            )
        return [_request_event(sequence, tool, call_id, row)], 1

    if method == "notifications/tools/call_result":
        event = _responded_event(sequence, row)
        if event is None:
            raise InputError(
                "tools/call_result row requires string params.tool and params.callId",
                details={"method": method, "reason": "missing_result_fields"},
            )
        return [event], 1

    if method in METHODS:
        return [_extension_event(sequence, method, row)], 1

    raise InputError(
        "unrecognized MCP JSONL method",
        details={"method": method, "reason": "unknown_method"},
    )


def mcp_lines_to_events(
    rows: list[dict[str, Any]],
    *,
    max_rows: int = 10_000,
    producer: str = "mcp",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert MCP JSON-RPC JSONL rows into vouchline-compatible input rows.

    Returns ``(events, metadata)`` where metadata carries ``source_format``
    and ``producer`` so the caller can record provenance in the artifact.
    """
    if max_rows < 1:
        raise InputError("max_rows must be positive", details={"max_rows": max_rows})

    bounded = rows[:max_rows]
    events: list[dict[str, Any]] = []
    sequence = 1
    for row_number, row in enumerate(bounded, start=1):
        if not isinstance(row, dict):
            raise InputError(
                "each MCP JSONL record must be an object",
                details={"line": row_number, "reason": "record_not_object"},
            )
        converted, used = _row_to_events(sequence, row)
        events.extend(converted)
        sequence += used

    return events, {
        "source_format": MCP_FORMAT_VERSION,
        "producer": producer,
        "rows_processed": len(bounded),
        "truncated": len(rows) > max_rows,
    }
