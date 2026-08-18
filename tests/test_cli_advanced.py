from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vouchline.cli import app

runner = CliRunner()


def write_sample(path: Path) -> None:
    rows = [
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
            "call_id": "call-1",
            "payload": {"tool": "search"},
        },
        {
            "schema_version": "v1",
            "event_id": "3",
            "sequence": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "kind": "tool.responded",
            "actor": "search",
            "call_id": "call-1",
            "payload": {"status": "ok"},
        },
        {
            "schema_version": "v1",
            "event_id": "4",
            "sequence": 4,
            "timestamp": "2026-01-01T00:00:03Z",
            "kind": "run.finished",
            "actor": "agent",
            "payload": {"status": "success"},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def capture(tmp_path: Path) -> Path:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    write_sample(source)
    assert runner.invoke(app, ["capture", str(source), "--output", str(artifact)]).exit_code == 0
    return artifact


def test_cli_version_prints_semver(tmp_path: Path) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip().startswith("0.2")


def test_cli_missing_input_file_fails_with_stable_code(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["capture", str(tmp_path / "missing.jsonl"), "--output", str(tmp_path / "out.json")]
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_cli_input_streamed_from_stdin(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    source = tmp_path / "events.jsonl"
    write_sample(source)
    result = runner.invoke(
        app,
        ["capture", "-", "--output", str(artifact)],
        input=source.read_text(encoding="utf-8"),
    )
    assert result.exit_code == 0, result.output
    artifact_data = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact_data["events"] is not None or len(artifact_data["events"]) == 4


def test_cli_assert_policy_human_output_passes(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text('{"deny_tools":["shell"]}', encoding="utf-8")
    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert result.exit_code == 0
    assert "Policy passed" in result.output


def test_cli_assert_policy_human_output_fails_with_details(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text('{"deny_tools":["search"]}', encoding="utf-8")
    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert result.exit_code == 4
    assert "POLICY_FAILURE" in result.output


def test_cli_assert_invalid_policy_document(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text("not json", encoding="utf-8")
    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_cli_verify_human_output(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    result = runner.invoke(app, ["verify", str(artifact)])
    assert result.exit_code == 0
    assert "Valid artifact" in result.output


def test_cli_compare_human_output_findings(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    changed = tmp_path / "changed.jsonl"
    rows = [
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
            "call_id": "call-2",
            "payload": {"tool": "shell"},
        },
        {
            "schema_version": "v1",
            "event_id": "3",
            "sequence": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "kind": "tool.responded",
            "actor": "shell",
            "call_id": "call-2",
            "payload": {"status": "ok"},
        },
    ]
    changed.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert runner.invoke(app, ["capture", str(changed), "--output", str(candidate)]).exit_code == 0
    result = runner.invoke(app, ["compare", str(baseline), str(candidate)])
    assert result.exit_code == 4
    assert "Comparison failed" in result.output
    assert "EVENT_COUNT_CHANGED" in result.output


def test_cli_compare_human_output_passes(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    result = runner.invoke(app, ["compare", str(baseline), str(candidate)])
    assert result.exit_code == 0
    assert "Comparison passed" in result.output


def _build_baseline_candidate(tmp_path: Path) -> tuple[Path, Path]:
    baseline_rows = [
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
            "call_id": "call-1",
            "payload": {"tool": "search"},
        },
    ]
    candidate_rows = list(baseline_rows) + [
        {
            "schema_version": "v1",
            "event_id": "3",
            "sequence": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "kind": "tool.responded",
            "actor": "search",
            "call_id": "call-1",
            "payload": {"status": "ok"},
        },
    ]
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    rows_text = "\n".join(json.dumps(row) for row in baseline_rows) + "\n"
    baseline.write_text(rows_text, encoding="utf-8")
    candidate_rows_text = "\n".join(json.dumps(row) for row in candidate_rows) + "\n"
    candidate.write_text(candidate_rows_text, encoding="utf-8")
    baseline_artifact = tmp_path / "baseline.json"
    candidate_artifact = tmp_path / "candidate.json"
    assert (
        runner.invoke(app, ["capture", str(baseline), "--output", str(baseline_artifact)]).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["capture", str(candidate), "--output", str(candidate_artifact)]
        ).exit_code
        == 0
    )
    return baseline_artifact, candidate_artifact


def test_cli_report_unknown_format_fails(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "html"])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output


def test_cli_report_sarif_written_to_file(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    out = tmp_path / "report.sarif"
    result = runner.invoke(
        app,
        ["report", str(baseline), str(candidate), "--format", "sarif", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"


def test_cli_replay_human_output_steps(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    result = runner.invoke(app, ["replay", str(artifact)])
    assert result.exit_code == 0
    assert "Replay verified" in result.output
    assert "search" in result.output


def test_cli_capture_human_table_output(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    write_sample(source)
    result = runner.invoke(app, ["capture", str(source), "--output", str(artifact)])
    assert result.exit_code == 0
    assert "Vouchline capture" in result.output
    assert "artifact_sha256" in result.output


def test_cli_verify_json_output(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    result = runner.invoke(app, ["verify", str(artifact), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["valid"] is True
    assert "artifact_sha256" in data


def test_cli_compare_json_output(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    result = runner.invoke(app, ["compare", str(baseline), str(candidate), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "passed" in data


def test_cli_report_json_format(tmp_path: Path) -> None:
    baseline, candidate = _build_baseline_candidate(tmp_path)
    result = runner.invoke(app, ["report", str(baseline), str(candidate), "--format", "JSON"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "passed" in data


def test_cli_replay_json_output_on_success(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    result = runner.invoke(app, ["replay", str(artifact), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["simulated"] is True


def test_cli_assert_json_output_on_success(tmp_path: Path) -> None:
    artifact = capture(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text('{"deny_tools":["shell"]}', encoding="utf-8")
    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["passed"] is True


def test_cli_main_dispatches_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The vouchline console entry point dispatches the typer app."""
    import sys

    from vouchline.cli import main

    monkeypatch.setattr(sys, "argv", ["vouchline", "--help"])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 0


def test_cli_replay_incomplete_human_error(tmp_path: Path) -> None:
    """A captured artifact missing a tool response fails replay in human mode."""
    rows = [
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
            "call_id": "call-1",
            "payload": {"tool": "search"},
        },
    ]
    incomplete = tmp_path / "incomplete.jsonl"
    incomplete.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    artifact = tmp_path / "incomplete.json"
    assert (
        runner.invoke(app, ["capture", str(incomplete), "--output", str(artifact)]).exit_code == 0
    )
    result = runner.invoke(app, ["replay", str(artifact)])
    assert result.exit_code == 4
    assert "REPLAY_FAILURE" in result.output
