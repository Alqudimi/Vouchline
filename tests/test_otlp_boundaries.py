from __future__ import annotations

import pytest

from vouchline.adapters import spans_to_events
from vouchline.errors import InputError

BASE = {
    "spanId": "abc",
    "name": "execute_tool",
    "startTimeUnixNano": "1767225600000000000",
    "attributes": [
        {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
        {"key": "gen_ai.tool.name", "value": {"stringValue": "search"}},
    ],
    "status": {"code": "STATUS_CODE_OK"},
}


def _payload(spans: list[object]) -> dict[str, list[dict[str, list[dict[str, list[object]]]]]]:
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def test_attribute_without_key_string_is_ignored() -> None:
    """Attributes whose key is not a string are skipped rather than raising."""
    span = dict(BASE, attributes=[{"value": {"stringValue": "search"}}, {"key": "ok", "value": {}}])
    events = spans_to_events(_payload([span]))
    assert events[0]["kind"] == "tool.requested"
    assert events[0]["call_id"] == "abc"


def test_attribute_without_dict_value_is_ignored() -> None:
    """Attributes whose value is not a structured object are skipped."""
    span = dict(
        BASE,
        attributes=[
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": "search"},
        ],
    )
    events = spans_to_events(_payload([span]))
    assert events[0]["payload"]["tool"] == "execute_tool"
    assert "stringValue" not in str(events[0]["payload"])


def test_attribute_value_picks_string_value_first() -> None:
    """The first known typed value wins when multiple value keys are present."""
    span = dict(
        BASE,
        attributes=[
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "ignored", "intValue": 42}},
        ],
    )
    events = spans_to_events(_payload([span]))
    assert events[0]["payload"]["tool"] == "ignored"


def test_attribute_value_picks_int_and_bool_fallbacks() -> None:
    """Known typed values inside a structured object are extracted.

    Plain non-dict values are skipped by _attributes, so this asserts the
    extraction order of intValue and boolValue inside valid attribute values.
    """
    span = dict(
        BASE,
        attributes=[
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"intValue": 7}},
        ],
    )
    events = spans_to_events(_payload([span]))
    assert events[0]["payload"]["tool"] == "7"

    span = dict(
        BASE,
        attributes=[
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"doubleValue": 3.5}},
        ],
    )
    events = spans_to_events(_payload([span]))
    assert events[0]["payload"]["tool"] == "3.5"


def test_non_dict_resources_are_skipped() -> None:
    span = dict(BASE, spanId="abc")
    events = spans_to_events(
        {"resourceSpans": [1, "bad", None, {"scopeSpans": [{"spans": [span]}]}]}
    )
    assert [event["call_id"] for event in events] == ["abc", "abc"]


def test_non_dict_scopes_are_skipped() -> None:
    span = dict(BASE, spanId="abc")
    events = spans_to_events({"resourceSpans": [{"scopeSpans": [1, {"spans": [span]}]}]})
    assert [event["call_id"] for event in events] == ["abc", "abc"]


def test_non_dict_span_is_ignored() -> None:
    """Non-dict entries inside the spans array are ignored."""
    events = spans_to_events(_payload([1, "bad", None, dict(BASE, spanId="abc")]))
    assert [event["call_id"] for event in events] == ["abc", "abc"]


def test_span_without_span_id_or_name_is_dropped() -> None:
    events = spans_to_events(_payload([{"spanId": "abc"}, {"name": "execute_tool"}, {}]))
    assert events == []


def test_otlp_max_spans_bounds_event_count() -> None:
    spans = [
        {
            "spanId": f"span-{index}",
            "name": "execute_tool",
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            ],
            "status": {"code": "STATUS_CODE_ERROR"},
        }
        for index in range(6)
    ]
    events = spans_to_events(_payload(spans), max_spans=2)
    assert len(events) == 4
    assert events[1]["payload"]["status"] == "error"


def test_otlp_non_tool_span_keeps_raw_attributes() -> None:
    span = {
        "spanId": "s1",
        "name": "chat",
        "attributes": [
            {"key": "mcp.server.name", "value": {"stringValue": "files"}},
        ],
    }
    events = spans_to_events(_payload([span]))
    assert events[0]["kind"] == "extension.otlp.span"
    assert events[0]["payload"]["attributes"] == {"mcp.server.name": "files"}


def test_missing_start_time_falls_back_to_current_utc() -> None:
    events = spans_to_events(
        {
            "resourceSpans": [
                {"scopeSpans": [{"spans": [{"spanId": "s1", "name": "chat", "attributes": []}]}]}
            ]
        }
    )
    assert events[0]["timestamp"].endswith("+00:00")


def test_empty_resource_spans_list_yields_no_events() -> None:
    assert spans_to_events({"resourceSpans": []}) == []


def test_missing_resource_spans_raises_input_error() -> None:
    with pytest.raises(InputError):
        spans_to_events({"resources": []})


def test_max_spans_negative_raises_input_error() -> None:
    with pytest.raises(InputError) as raised:
        spans_to_events({"resourceSpans": []}, max_spans=-1)
    assert raised.value.code == "INVALID_INPUT"
    assert raised.value.details == {"max_spans": -1}
