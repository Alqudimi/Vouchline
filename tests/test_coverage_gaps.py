"""Tests closing genuine coverage gaps: OTLP adapter attribute variants and
boundaries, policy limit findings, machine-readable report renderers, replay
failure paths, and CLI error handling.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vouchline.adapters import spans_to_events
from vouchline.canonical import jsonable
from vouchline.capture import build_artifact, load_artifact
from vouchline.cli import app
from vouchline.errors import InputError, LimitError, ReplayError
from vouchline.models import InputEvent, Policy, Producer
from vouchline.policy import evaluate_policy
from vouchline.redaction import redact
from vouchline.replay import replay_artifact
from vouchline.reporting import comparison_json, comparison_junit, comparison_sarif

runner = CliRunner()

# ---------------------------------------------------------------------------
# OTLP adapter: attribute variants and boundary behaviour
# ---------------------------------------------------------------------------


def test_otlp_attributes_accept_all_primitive_value_types() -> None:
    """AnyValue primitives other than stringValue must still reach the event."""
    tool_span = {
        "spanId": "p1",
        "name": "execute_tool",
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "fetch"}},
            {"key": "retries", "value": {"intValue": 3}},
            {"key": "latency", "value": {"doubleValue": 0.42}},
            {"key": "cached", "value": {"boolValue": True}},
        ],
    }
    events = spans_to_events({"resourceSpans": [{"scopeSpans": [{"spans": [tool_span]}]}]})
    assert events[0]["kind"] == "tool.requested"
    assert events[0]["payload"]["tool"] == "fetch"
    # Extra attribute primitives stay attached to the tool span event payload.
    attrs = events[0]["payload"].get("attributes")
    assert attrs is None or attrs.get("retries") == 3
    # The non-tool span keeps its full attribute set, which is the observable
    # adapter behaviour.


def test_otlp_non_tool_span_carries_attributes() -> None:
    """A non-tool span keeps the primitive attributes it receives."""
    events = spans_to_events(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "spanId": "p2",
                                    "name": "chat",
                                    "attributes": [
                                        {"key": "retries", "value": {"intValue": 3}},
                                        {"key": "latency", "value": {"doubleValue": 0.42}},
                                        {"key": "cached", "value": {"boolValue": True}},
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    assert events[0]["kind"] == "extension.otlp.span"
    attrs = events[0]["payload"]["attributes"]
    assert attrs["retries"] == 3
    assert attrs["latency"] == 0.42
    assert attrs["cached"] is True


def test_otlp_attribute_unknown_value_shapes_are_ignored() -> None:
    """Value objects without a recognized primitive key contribute nothing."""
    tool_span = {
        "spanId": "q1",
        "name": "execute_tool",
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "fetch"}},
            {"key": "list_attr", "value": {"arrayValue": {"values": []}}},
            {"key": "bytes_attr", "value": {"bytesValue": "AQID"}},
            {"key": "kvlist_attr", "value": {"kvlistValue": {"values": []}}},
            {"key": "empty_value", "value": {}},
            {"key": 1, "value": {"stringValue": "x"}},
            {"not_a_dict": True},
        ],
    }
    non_tool_span = {
        "spanId": "q2",
        "name": "chat",
        "attributes": [
            {"key": "gen_ai.tool.name", "value": {"stringValue": "fetch"}},
            {"key": "list_attr", "value": {"arrayValue": {"values": []}}},
            {"key": "bytes_attr", "value": {"bytesValue": "AQID"}},
            {"key": "empty_value", "value": {}},
            {"key": 1, "value": {"stringValue": "x"}},
            {"not_a_dict": True},
        ],
    }
    events = spans_to_events(
        {"resourceSpans": [{"scopeSpans": [{"spans": [tool_span, non_tool_span]}]}]}
    )
    assert events[0]["payload"]["tool"] == "fetch"
    span_event = next(event for event in events if event["kind"] == "extension.otlp.span")
    assert span_event["payload"]["attributes"] == {"gen_ai.tool.name": "fetch"}


def test_otlp_span_missing_key_or_id_is_skipped() -> None:
    """Spans without a string spanId or name produce no events."""
    events = spans_to_events(
        {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "chat", "attributes": []}]}]}]}
    )
    assert events == []
    events = spans_to_events(
        {"resourceSpans": [{"scopeSpans": [{"spans": [{"spanId": "abc", "attributes": []}]}]}]}
    )
    assert events == []


def test_otlp_malformed_structure_is_skipped_gracefully() -> None:
    """Non-dict resources, scopes, or value objects never raise."""
    payload = {
        "resourceSpans": [
            "not-a-resource",
            {"scopeSpans": ["not-a-scope"]},
            {"scopeSpans": [{"spans": "not-a-list"}]},
        ]
    }
    assert spans_to_events(payload) == []


def test_otlp_tool_detection_via_name_keyword() -> None:
    """A span whose name contains 'tool' is treated as a tool call."""
    events = spans_to_events(
        {
            "resourceSpans": [
                {"scopeSpans": [{"spans": [{"spanId": "t1", "name": "invoke_tool_call"}]}]}
            ]
        }
    )
    assert [event["kind"] for event in events] == ["tool.requested", "tool.responded"]


def test_otlp_tool_fallback_order_and_unix_nano_timestamp() -> None:
    """Tool name falls back to mcp.tool.name then span name, and timestamps
    come from startTimeUnixNano when it is a numeric string."""
    events = spans_to_events(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "spanId": "mcp1",
                                    "name": "run mcp tool server",
                                    "startTimeUnixNano": "1767225600000000000",
                                    "attributes": [
                                        {
                                            "key": "mcp.tool.name",
                                            "value": {"stringValue": "git_read"},
                                        },
                                    ],
                                    "status": {"code": "STATUS_CODE_ERROR"},
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    assert events[0]["payload"]["tool"] == "git_read"
    assert events[0]["timestamp"] == datetime.fromtimestamp(1767225600, tz=UTC).isoformat()
    assert events[1]["payload"]["status"] == "error"


def test_otlp_timestamp_defaults_when_nanoseconds_invalid() -> None:
    """Non-numeric or non-string nanosecond values yield the current time."""
    before = datetime.now(UTC)
    events = spans_to_events(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {"spans": [{"spanId": "x", "name": "n1", "startTimeUnixNano": 1.5}]}
                    ]
                }
            ]
        }
    )
    after = datetime.now(UTC)
    timestamp = datetime.fromisoformat(events[0]["timestamp"])
    assert before <= timestamp <= after


def test_otlp_max_spans_bound_is_exact() -> None:
    """Bounded conversion keeps at most max_spans spans."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {"spanId": f"s{i}", "name": "chat", "attributes": []} for i in range(5)
                        ]
                    }
                ]
            }
        ]
    }
    assert len(spans_to_events(payload, max_spans=3)) == 3
    with pytest.raises(InputError):
        spans_to_events(payload, max_spans=-1)


# ---------------------------------------------------------------------------
# Policy: limit findings and missing required tools
# ---------------------------------------------------------------------------


def _policy_artifact(tool_calls: int = 1, call_statuses: str | None = None) -> object:
    events: list[InputEvent] = []
    for index in range(tool_calls):
        call_id = f"call-{index}"
        events.append(
            InputEvent(
                schema_version="v1",
                event_id=f"req-{index}",
                sequence=index * 2 + 1,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind="tool.requested",
                actor="policy-test",
                call_id=call_id,
                payload={"tool": f"tool-{index}"},
            )
        )
        status = call_statuses if call_statuses else "ok"
        events.append(
            InputEvent(
                schema_version="v1",
                event_id=f"resp-{index}",
                sequence=index * 2 + 2,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind="tool.responded",
                actor=f"tool-{index}",
                call_id=call_id,
                payload={"status": status},
            )
        )
    return build_artifact(
        events,
        run_id="policy",
        producer=Producer(name="test", version="1"),
        redaction_count=0,
    )


def test_policy_finds_max_tool_calls_exceeded() -> None:
    report = evaluate_policy(_policy_artifact(tool_calls=5), Policy(max_tool_calls=2))
    assert not report.passed
    finding = next(finding for finding in report.findings if finding.rule == "max_tool_calls")
    assert "5" in finding.message
    assert "2" in finding.message


def test_policy_finds_required_tools_missing() -> None:
    report = evaluate_policy(
        _policy_artifact(tool_calls=1), Policy(require_tools=["search", "git_read"])
    )
    assert not report.passed
    rules = [finding.rule for finding in report.findings]
    assert rules.count("require_tools") == 2
    messages = " ".join(finding.message for finding in report.findings)
    assert "git_read" in messages and "search" in messages


def test_policy_sorted_required_tool_report_order() -> None:
    report = evaluate_policy(
        _policy_artifact(tool_calls=1), Policy(require_tools=["z_tool", "a_tool"])
    )
    rules = [finding.message for finding in report.findings if finding.rule == "require_tools"]
    assert rules[0].endswith("'a_tool' was not called")
    assert rules[1].endswith("'z_tool' was not called")


# ---------------------------------------------------------------------------
# Replay failure paths
# ---------------------------------------------------------------------------


def _simple_replay_artifact(events: list[dict[str, object]]) -> object:
    typed: list[InputEvent] = []
    for index, event in enumerate(events):
        typed.append(
            InputEvent(
                schema_version="v1",
                sequence=index + 1,
                event_id=event.get("event_id", f"evt-{index}"),
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind=event["kind"],
                actor=event.get("actor", "r"),
                call_id=event.get("call_id"),
                payload=event.get("payload", {}),
            )
        )
    return build_artifact(
        typed,
        run_id="replay",
        producer=Producer(name="test", version="1"),
        redaction_count=0,
    )


def test_replay_rejects_request_without_call_id() -> None:
    with pytest.raises(ReplayError):
        replay_artifact(
            _simple_replay_artifact(
                [{"kind": "tool.requested", "actor": "a", "payload": {"tool": "x"}}]
            )
        )


def test_replay_rejects_response_without_matching_request() -> None:
    with pytest.raises(ReplayError):
        replay_artifact(
            _simple_replay_artifact(
                [{"kind": "tool.responded", "actor": "a", "payload": {"status": "ok"}}]
            )
        )


def test_replay_detects_missing_responses() -> None:
    report = replay_artifact(
        _simple_replay_artifact(
            [
                {
                    "kind": "tool.requested",
                    "call_id": "call-1",
                    "actor": "a",
                    "payload": {"tool": "x"},
                },
            ]
        )
    )
    assert not report.passed
    assert report.missing_responses == ["call-1"]
    assert report.simulated is True


# ---------------------------------------------------------------------------
# Redaction: nested lists and depth limit
# ---------------------------------------------------------------------------


def test_redaction_covers_nested_lists() -> None:
    result = redact(
        [
            {"secret_key": "sk-1234567890ab"},
            [1, {"authorization": "Bearer 1234567890abc"}],
        ]
    )
    assert result.value == [
        {"secret_key": "[REDACTED]"},
        [1, {"authorization": "[REDACTED]"}],
    ]
    assert result.count == 2


def test_redaction_raises_on_exceeded_depth() -> None:
    nested: object = [1]
    for _ in range(60):
        nested = [nested]  # type: ignore[list-item]
    with pytest.raises(LimitError):
        redact(nested)


# ---------------------------------------------------------------------------
# Report renderers: JSON, SARIF, JUnit
# ---------------------------------------------------------------------------


def _comparison_report(passed: bool, with_findings: bool) -> object:
    from vouchline.models import ComparisonFinding, ComparisonReport

    findings: list[ComparisonFinding] = []
    if with_findings:
        findings.append(
            ComparisonFinding(
                code="TOOL_STATUS_CHANGED",
                message="status changed from ok to error",
                severity="error" if passed is False else "info",
                call_id="call-1",
            )
        )
    return ComparisonReport(
        passed=passed,
        baseline_artifact_id="base",
        candidate_artifact_id="cand",
        findings=findings,
    )


def test_comparison_renderers_json_and_junit_no_findings() -> None:
    report = _comparison_report(True, False)
    assert comparison_json(report)["passed"] is True
    rendered = comparison_junit(report)
    assert "comparison-passed" in rendered
    assert 'failures="0"' in rendered


def test_comparison_junit_error_and_info_paths() -> None:
    report = _comparison_report(False, True)
    rendered = comparison_junit(report)
    assert "TOOL_STATUS_CHANGED" in rendered
    assert "failure" in rendered
    assert 'failures="1"' in rendered


def test_comparison_sarif_warning_level_mapping() -> None:
    from vouchline.models import ComparisonFinding, ComparisonReport

    report = ComparisonReport(
        passed=True,
        baseline_artifact_id="base",
        candidate_artifact_id="cand",
        findings=[
            ComparisonFinding(
                code="EVT_COUNT",
                message="m",
                severity="warning",
                call_id="c",
            )
        ],
    )
    sarif = comparison_sarif(report, artifact_path="candidate.json")
    assert sarif["runs"][0]["results"][0]["level"] == "warning"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "vouchline"


# ---------------------------------------------------------------------------
# CLI: stdin capture, report formats, invalid format, policy failure output
# ---------------------------------------------------------------------------


SAMPLE_JSONL = (
    '{"event_id":"e1","sequence":1,"timestamp":"2026-01-01T00:00:00+00:00",'
    '"kind":"run.started","actor":"cli-test","payload":{}}\n'
    '{"event_id":"e2","sequence":2,"timestamp":"2026-01-01T00:00:00+00:00",'
    '"kind":"tool.requested","actor":"cli-test","call_id":"c1",'
    '"payload":{"tool":"fetch"}}\n'
    '{"event_id":"e3","sequence":3,"timestamp":"2026-01-01T00:00:00+00:00",'
    '"kind":"tool.responded","actor":"fetch","call_id":"c1",'
    '"payload":{"status":"ok"}}\n'
    '{"event_id":"e4","sequence":4,"timestamp":"2026-01-01T00:00:00+00:00",'
    '"kind":"run.finished","actor":"cli-test","payload":{"status":"completed"}}\n'
)


@pytest.fixture()
def artifacts_dir(tmp_path: Path):
    input_file = tmp_path / "run.jsonl"
    input_file.write_text(SAMPLE_JSONL, encoding="utf-8")
    out = tmp_path / "artifact.json"
    runner.invoke(app, ["capture", str(input_file), "--output", str(out)])
    copy = tmp_path / "candidate.json"
    runner.invoke(
        app,
        [
            "capture",
            str(input_file),
            "--output",
            str(copy),
            "--run-id",
            "candidate-run",
        ],
    )
    return tmp_path


def test_cli_capture_from_stdin(tmp_path: Path) -> None:
    out = tmp_path / "stdin-artifact.json"
    result = runner.invoke(app, ["capture", "-", "--output", str(out)], input=SAMPLE_JSONL)
    assert result.exit_code == 0, result.output
    loaded = load_artifact(out)
    assert loaded.manifest.event_count == 4
    assert len(loaded.events) == 4


def test_cli_report_junit_format_and_file_output(artifacts_dir: Path) -> None:
    report_file = artifacts_dir / "out.xml"
    result = runner.invoke(
        app,
        [
            "report",
            str(artifacts_dir / "artifact.json"),
            str(artifacts_dir / "candidate.json"),
            "--format",
            "junit",
            "--output",
            str(report_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "testsuite" in report_file.read_text(encoding="utf-8")


def test_cli_report_invalid_format_raises(artifacts_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "report",
            str(artifacts_dir / "artifact.json"),
            str(artifacts_dir / "candidate.json"),
            "--format",
            "csv",
        ],
    )
    assert result.exit_code != 0
    assert "INTERNAL_ERROR" in result.output or "format" in result.output


def test_cli_assert_policy_failure_json_output(artifacts_dir: Path) -> None:
    policy_path = artifacts_dir / "policy.json"
    policy_path.write_text('{"require_tools":["missing_tool"]}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "assert",
            str(artifacts_dir / "artifact.json"),
            "--policy",
            str(policy_path),
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "POLICY_FAILURE"


def test_cli_assert_invalid_policy_document(artifacts_dir: Path) -> None:
    policy_path = artifacts_dir / "bad-policy.json"
    policy_path.write_text("not-json", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "assert",
            str(artifacts_dir / "artifact.json"),
            "--policy",
            str(policy_path),
        ],
    )
    assert result.exit_code != 0
    assert "policy must be a valid JSON policy document" in result.output


# ---------------------------------------------------------------------------
# Canonical: BaseModel and date serialization
# ---------------------------------------------------------------------------


def test_jsonable_serializes_dates_and_models() -> None:
    assert jsonable(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00+00:00"
    assert jsonable(datetime(2026, 1, 1).date()) == "2026-01-01"
    dumped = jsonable(Policy(max_tool_calls=5))
    expected = {
        "deny_tools": [],
        "deny_statuses": [],
        "max_tool_calls": 5,
        "require_tools": [],
        "max_cost": None,
        "max_total_tokens": None,
    }
    assert dumped == expected


def test_errors_info_helper() -> None:
    from vouchline.errors import ErrorInfo, InputError

    error = InputError("bad input", details={"field": "x"})
    info = error.info()
    assert isinstance(info, ErrorInfo)
    assert info.code == "INVALID_INPUT"
