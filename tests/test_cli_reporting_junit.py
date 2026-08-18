"""CLI boundary and output-format tests covering previously unexercised paths.

Documents the terminal and machine-readable contracts for every CLI command,
the junit/sarif/JSON report formats, and boundary behaviour on hostile input.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from typer.testing import CliRunner

from vouchline.capture import build_artifact, write_artifact
from vouchline.cli import app
from vouchline.models import InputEvent, Producer

runner = CliRunner()

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


def _build(path: Path, run_id: str, events: list[InputEvent]) -> None:
    write_artifact(
        path, build_artifact(events, run_id=run_id, producer=PRODUCER, redaction_count=0)
    )


def _build_fixed(path: Path, run_id: str, events: list[InputEvent]) -> None:
    """Build with a fixed artifact id and timestamp to test deterministic output."""
    write_artifact(
        path,
        build_artifact(
            events,
            run_id=run_id,
            producer=PRODUCER,
            redaction_count=0,
            artifact_id="fixed-artifact-id",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def _jsonl(source: Path, rows: list[dict[str, object]]) -> None:
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_capture_writes_artifact_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    _jsonl(
        source,
        [
            {
                "schema_version": "v1",
                "event_id": "1",
                "sequence": 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "kind": "run.started",
                "actor": "agent",
                "payload": {},
            },
            {
                "schema_version": "v1",
                "event_id": "2",
                "sequence": 2,
                "timestamp": "2026-01-01T00:00:01Z",
                "kind": "tool.requested",
                "actor": "agent",
                "call_id": "c1",
                "payload": {"tool": "search"},
            },
            {
                "schema_version": "v1",
                "event_id": "3",
                "sequence": 3,
                "timestamp": "2026-01-01T00:00:02Z",
                "kind": "tool.responded",
                "actor": "search",
                "call_id": "c1",
                "payload": {"status": "ok"},
            },
        ],
    )
    result = runner.invoke(app, ["capture", str(source), "--output", str(artifact), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["event_count"] == 3
    assert artifact.exists()
    # Artifact bytes must be canonical/deterministic for hash-chain integrity:
    # building the same events twice with a fixed artifact id and timestamp
    # must produce byte-equal output.
    events = [
        _event(1, "run.started", {"task": "t"}),
        _event(2, "tool.requested", {"tool": "search"}, "c1"),
        _event(3, "tool.responded", {"status": "ok"}, "c1"),
    ]
    first = tmp_path / "artifact-1.json"
    second = tmp_path / "artifact-2.json"
    _build_fixed(first, "run-1", events)
    _build_fixed(second, "run-1", events)
    assert second.read_bytes() == first.read_bytes(), (
        "artifact output must be deterministic so that hash-chain verification is reproducible"
    )
    # Hash chain integrity survives the second write as well.
    verify = runner.invoke(app, ["verify", str(second)])
    assert verify.exit_code == 0, verify.output


def test_capture_missing_input_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["capture", str(tmp_path / "missing.jsonl"), "--output", str(tmp_path / "artifact.json")],
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output
    assert "missing" in result.output


def test_capture_corrupted_jsonl(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text("{not valid json\n", encoding="utf-8")
    result = runner.invoke(
        app, ["capture", str(source), "--output", str(tmp_path / "artifact.json")]
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_capture_limit_error_when_max_events_exceeded(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    rows = [
        {
            "schema_version": "v1",
            "event_id": str(i),
            "sequence": i,
            "timestamp": "2026-01-01T00:00:00Z",
            "kind": "run.started",
            "actor": "agent",
            "payload": {},
        }
        for i in range(1, 11)
    ]
    _jsonl(source, rows)
    result = runner.invoke(
        app,
        ["capture", str(source), "--output", str(tmp_path / "artifact.json"), "--max-events", "5"],
    )
    assert result.exit_code == 2
    assert "INPUT_LIMIT_EXCEEDED" in result.output


def test_verify_fails_on_tampered_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "run.finished", {"status": "completed"}),
        ],
    )
    raw = json.loads(artifact.read_text(encoding="utf-8"))
    raw["producer"]["name"] = "tampered"
    artifact.write_text(json.dumps(raw), encoding="utf-8")
    result = runner.invoke(app, ["verify", str(artifact), "--json"])
    assert result.exit_code == 3
    assert "INTEGRITY_FAILURE" in result.output


def test_verify_corrupted_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{corrupted", encoding="utf-8")
    result = runner.invoke(app, ["verify", str(artifact)])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_verify_missing_artifact(tmp_path: Path) -> None:
    # typer validates the readable-path argument before the handler runs,
    # so a missing artifact fails at the CLI boundary with exit code 2.
    result = runner.invoke(app, ["verify", str(tmp_path / "missing.json")])
    assert result.exit_code == 2


def test_compare_terminal_paths(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _build(
        baseline,
        "run-1",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "run.finished", {"status": "completed"}),
        ],
    )
    _build(
        candidate,
        "run-2",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "run.finished", {"status": "completed"}),
        ],
    )
    passed = runner.invoke(app, ["compare", str(baseline), str(candidate)])
    assert passed.exit_code == 0
    assert "Comparison passed." in passed.output

    # Changing an outcome produces a failed comparison with human-readable output.
    _build(
        candidate,
        "run-3",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "tool.requested", {"tool": "search"}, "c1"),
            _event(3, "tool.responded", {"status": "timeout"}, "c1"),
        ],
    )
    failed = runner.invoke(app, ["compare", str(baseline), str(candidate)])
    assert failed.exit_code == 4
    assert "Comparison failed." in failed.output


def test_compare_same_artifact_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "a.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "run.finished", {"status": "completed"}),
        ],
    )
    result = runner.invoke(app, ["compare", str(artifact), str(artifact), "--json"])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_compare_json_machine_output(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    _build(
        baseline,
        "run-1",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    _build(
        candidate,
        "run-2",
        [
            _event(1, "tool.requested", {"tool": "fetch"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    result = runner.invoke(app, ["compare", str(baseline), str(candidate), "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    codes = {finding["code"] for finding in payload["findings"]}
    assert "TOOL_CHANGED" in codes


def test_report_junit_format(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    _build(
        baseline,
        "run-1",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    _build(
        candidate,
        "run-2",
        [
            _event(1, "tool.requested", {"tool": "fetch"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "junit"])
    assert result.exit_code == 4, result.output
    root = ElementTree.fromstring(result.output)
    assert root.tag == "testsuite"
    assert root.find(".//failure") is not None


def test_report_sarif_format(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    _build(
        baseline,
        "run-1",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    _build(
        candidate,
        "run-2",
        [
            _event(1, "tool.requested", {"tool": "fetch"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "sarif"])
    assert result.exit_code == 4, result.output
    sarif = json.loads(result.output)
    assert sarif["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    assert sarif["runs"][0]["results"]


def test_report_junit_passing_case(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    _build(
        baseline,
        "run-1",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    _build(
        candidate,
        "run-2",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "junit"])
    assert result.exit_code == 0, result.output
    root = ElementTree.fromstring(result.output)
    assert root.find(".//failure") is None
    assert root.find('.//testcase[@name="comparison-passed"]') is not None


def test_report_invalid_format(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    _build(baseline, "run-1", [_event(1, "run.started", {})])
    _build(candidate, "run-2", [_event(1, "run.started", {})])
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "xml"])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_report_writes_output_file(tmp_path: Path) -> None:
    baseline = tmp_path / "b.json"
    candidate = tmp_path / "c.json"
    out = tmp_path / "report.json"
    _build(baseline, "run-1", [_event(1, "run.started", {})])
    _build(candidate, "run-2", [_event(1, "run.started", {})])
    result = runner.invoke(
        app, ["report", str(baseline), str(candidate), "--format", "json", "--output", str(out)]
    )
    assert result.exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["passed"] is True


def test_replay_terminal_output(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "tool.requested", {"tool": "search"}, "c1"),
            _event(3, "tool.responded", {"status": "ok"}, "c1"),
            _event(4, "run.finished", {"status": "completed"}),
        ],
    )
    result = runner.invoke(app, ["replay", str(artifact)])
    assert result.exit_code == 0
    assert "Replay verified." in result.output
    assert "#2 search" in result.output


def test_replay_missing_responses_fails(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "tool.requested", {"tool": "search"}, "c1"),
            _event(2, "tool.requested", {"tool": "fetch"}, "c2"),
            _event(3, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    result = runner.invoke(app, ["replay", str(artifact), "--json"])
    # REPLAY_FAILURE is a user-actionable error at exit code 4 (per errors.py).
    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "REPLAY_FAILURE"
    assert set(payload["error"]["details"]["missing_responses"]) == {"c2"}


def test_replay_internal_invariant_missing_call_id(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "run.started", {}),
            InputEvent(
                event_id="e2",
                sequence=2,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind="tool.requested",
                actor="agent",
                call_id=None,
                payload={"tool": "search"},
            ),
            _event(3, "tool.responded", {"status": "ok"}, None),
        ],
    )
    result = runner.invoke(app, ["replay", str(artifact)])
    assert result.exit_code == 4
    assert "REPLAY_FAILURE" in result.output


def test_assert_terminal_pass_and_failure(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    policy = tmp_path / "policy.json"
    _build(
        artifact,
        "run-1",
        [
            _event(1, "run.started", {"task": "t"}),
            _event(2, "tool.requested", {"tool": "search"}, "c1"),
            _event(3, "tool.responded", {"status": "ok"}, "c1"),
        ],
    )
    policy.write_text('{"require_tools":["search"],"max_tool_calls":1}', encoding="utf-8")
    passed = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert passed.exit_code == 0
    assert "Policy passed." in passed.output

    policy.write_text('{"deny_tools":["search"]}', encoding="utf-8")
    failed = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert failed.exit_code == 4
    assert "POLICY_FAILURE" in failed.output


def test_assert_corrupted_policy(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    policy = tmp_path / "policy.json"
    _build(artifact, "run-1", [_event(1, "run.started", {})])
    policy.write_text("{broken", encoding="utf-8")
    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_normalize_mcp_terminal_output_and_limit(tmp_path: Path) -> None:
    source = tmp_path / "mcp.jsonl"
    source.write_text(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "normalized.jsonl"
    result = runner.invoke(app, ["normalize-mcp", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert "normalized" in result.output
    assert output.exists()

    result = runner.invoke(
        app, ["normalize-mcp", str(source), "--output", str(output), "--max-messages", "1"]
    )
    assert result.exit_code == 2
    assert "INPUT_LIMIT_EXCEEDED" in result.output


def test_normalize_mcp_corrupted_line(tmp_path: Path) -> None:
    source = tmp_path / "mcp.jsonl"
    source.write_text("not json at all\n", encoding="utf-8")
    result = runner.invoke(
        app, ["normalize-mcp", str(source), "--output", str(tmp_path / "out.jsonl")]
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_normalize_mcp_non_object_record(tmp_path: Path) -> None:
    source = tmp_path / "mcp.jsonl"
    source.write_text("[1, 2, 3]\n", encoding="utf-8")
    result = runner.invoke(
        app, ["normalize-mcp", str(source), "--output", str(tmp_path / "out.jsonl")]
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_normalize_mcp_skips_blank_lines(tmp_path: Path) -> None:
    source = tmp_path / "mcp.jsonl"
    source.write_text(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + "\n"
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "normalized.jsonl"
    result = runner.invoke(app, ["normalize-mcp", str(source), "--output", str(output)])
    assert result.exit_code == 0
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2


def test_canonical_serializes_dates(tmp_path: Path) -> None:
    """Artifact timestamps must serialize deterministically via canonical_bytes."""
    from vouchline.canonical import canonical_bytes

    payload = {"created_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)}
    assert canonical_bytes(payload) == b'{"created_at":"2026-01-01T12:00:00+00:00"}'


def test_main_entrypoint_emits_version(tmp_path: Path) -> None:
    """The __main__ entrypoint must be functional and delegate to the CLI app."""
    import subprocess

    from vouchline import __version__

    completed = subprocess.run(
        ["python3", "-m", "vouchline", "version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(__version__) in completed.stdout


def test_version_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vouchline import __version__

    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert str(__version__) in result.output
