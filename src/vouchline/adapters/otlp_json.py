"""Pure OTLP/JSON normalization into Vouchline input events.

The adapter only transforms supplied Python data. It never opens a socket,
imports an SDK, or executes a provider-specific action.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..errors import InputError


def _attributes(span: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in span.get("attributes", []):
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        value = item.get("value", {})
        if not isinstance(value, dict):
            continue
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in value:
                values[item["key"]] = value[key]
                break
    return values


def _timestamp(span: dict[str, Any]) -> str:
    raw = span.get("startTimeUnixNano")
    if isinstance(raw, str) and raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1_000_000_000, tz=UTC).isoformat()
    return datetime.now(UTC).isoformat()


def spans_to_events(payload: dict[str, Any], *, max_spans: int = 10_000) -> list[dict[str, Any]]:
    """Convert OTLP/JSON resource spans into vouchline-compatible input rows."""
    if max_spans < 1:
        raise InputError("max_spans must be positive", details={"max_spans": max_spans})
    resource_spans = payload.get("resourceSpans")
    if not isinstance(resource_spans, list):
        raise InputError("OTLP payload must contain resourceSpans as an array")

    spans: list[dict[str, Any]] = []
    for resource in resource_spans:
        if not isinstance(resource, dict):
            continue
        for scope in resource.get("scopeSpans", []):
            if not isinstance(scope, dict):
                continue
            for span in scope.get("spans", []):
                if isinstance(span, dict):
                    spans.append(span)
                    if len(spans) >= max_spans:
                        break
            if len(spans) >= max_spans:
                break
        if len(spans) >= max_spans:
            break

    events: list[dict[str, Any]] = []
    sequence = 1
    for span in spans:
        span_id = span.get("spanId")
        name = span.get("name")
        if not isinstance(span_id, str) or not isinstance(name, str):
            continue
        attrs = _attributes(span)
        kind = name.lower()
        if "tool" in kind or attrs.get("gen_ai.operation.name") == "execute_tool":
            tool = attrs.get("gen_ai.tool.name") or attrs.get("mcp.tool.name") or name
            events.append(
                {
                    "event_id": span_id + ":request",
                    "sequence": sequence,
                    "timestamp": _timestamp(span),
                    "kind": "tool.requested",
                    "actor": "otlp",
                    "call_id": span_id,
                    "payload": {"tool": str(tool), "source": "otlp"},
                }
            )
            sequence += 1
            status = "error" if span.get("status", {}).get("code") == "STATUS_CODE_ERROR" else "ok"
            events.append(
                {
                    "event_id": span_id + ":response",
                    "sequence": sequence,
                    "timestamp": _timestamp(span),
                    "kind": "tool.responded",
                    "actor": "otlp",
                    "call_id": span_id,
                    "payload": {"status": status, "source": "otlp"},
                }
            )
            sequence += 1
            continue
        events.append(
            {
                "event_id": span_id,
                "sequence": sequence,
                "timestamp": _timestamp(span),
                "kind": "extension.otlp.span",
                "actor": "otlp",
                "payload": {"name": name, "attributes": attrs},
            }
        )
        sequence += 1
    return events
