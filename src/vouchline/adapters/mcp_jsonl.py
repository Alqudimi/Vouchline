"""Pure MCP JSON-RPC transcript normalization.

This adapter accepts already-loaded JSON-RPC messages and never connects to an
MCP server. Persistence, redaction, and integrity remain owned by capture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..errors import InputError


def _timestamp(message: dict[str, Any]) -> str:
    value = message.get("timestamp")
    if isinstance(value, str):
        return value
    return datetime.now(UTC).isoformat()


def _call_id(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value)
    return None


def _method_name(message: dict[str, Any]) -> str | None:
    method = message.get("method")
    return method if isinstance(method, str) else None


def _tool_name(params: Any) -> str:
    if isinstance(params, dict):
        name = params.get("name")
        if isinstance(name, str) and name:
            return name
    return "unknown"


def messages_to_events(
    messages: list[dict[str, Any]], *, max_messages: int = 10_000
) -> list[dict[str, Any]]:
    """Convert MCP JSON-RPC transcript messages into Vouchline input rows."""
    if max_messages < 1:
        raise InputError("max_messages must be positive", details={"max_messages": max_messages})
    events: list[dict[str, Any]] = []
    for sequence, message in enumerate(messages[:max_messages], start=1):
        call_id = _call_id(message.get("id"))
        method = _method_name(message)
        timestamp = _timestamp(message)
        if method == "tools/call" and call_id is not None:
            events.append(
                {
                    "event_id": f"mcp-{call_id}-request",
                    "sequence": sequence,
                    "timestamp": timestamp,
                    "kind": "tool.requested",
                    "actor": "mcp",
                    "call_id": call_id,
                    "payload": {
                        "tool": _tool_name(message.get("params")),
                        "protocol": "mcp",
                        "params": message.get("params", {}),
                    },
                }
            )
            continue
        if call_id is not None and ("result" in message or "error" in message):
            error = message.get("error")
            status = "error" if isinstance(error, dict) else "ok"
            events.append(
                {
                    "event_id": f"mcp-{call_id}-response",
                    "sequence": sequence,
                    "timestamp": timestamp,
                    "kind": "tool.responded",
                    "actor": "mcp",
                    "call_id": call_id,
                    "payload": {
                        "status": status,
                        "protocol": "mcp",
                        "result": message.get("result"),
                        "error": error,
                    },
                }
            )
            continue
        events.append(
            {
                "event_id": f"mcp-message-{sequence}",
                "sequence": sequence,
                "timestamp": timestamp,
                "kind": "extension.mcp.message",
                "actor": "mcp",
                "payload": {
                    "method": method,
                    "id": message.get("id"),
                    "has_result": "result" in message,
                    "has_error": "error" in message,
                },
            }
        )
    return events
