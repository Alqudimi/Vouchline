from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vouchline.cli import app

runner = CliRunner()


def write_events(path: Path, *, status: str = "ok", tool: str = "search") -> None:
    rows = [
        {
            "event_id": "1",
            "sequence": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "kind": "run.started",
            "actor": "agent",
            "payload": {},
        },
        {
            "event_id": "2",
            "sequence": 2,
            "timestamp": "2026-01-01T00:00:01Z",
            "kind": "tool.requested",
            "actor": "agent",
            "call_id": "c1",
            "payload": {"tool": tool},
        },
        {
            "event_id": "3",
            "sequence": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "kind": "tool.responded",
            "actor": tool,
            "call_id": "c1",
            "payload": {"status": status},
        },
        {
            "event_id": "4",
            "sequence": 4,
            "timestamp": "2026-01-01T00:00:03Z",
            "kind": "run.finished",
            "actor": "agent",
            "payload": {"status": status},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def capture(source: Path, artifact: Path) -> None:
    result = runner.invoke(app, ["capture", str(source), "--output", str(artifact)])
    assert result.exit_code == 0, result.output


def test_compare_passes_for_identical_outcomes(tmp_path: Path) -> None:
    baseline_source = tmp_path / "baseline.jsonl"
    candidate_source = tmp_path / "candidate.jsonl"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    write_events(baseline_source)
    write_events(candidate_source)
    capture(baseline_source, baseline)
    capture(candidate_source, candidate)

    result = runner.invoke(app, ["compare", str(baseline), str(candidate), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["passed"] is True


def test_compare_and_reports_detect_regression(tmp_path: Path) -> None:
    baseline_source = tmp_path / "baseline.jsonl"
    candidate_source = tmp_path / "candidate.jsonl"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    sarif = tmp_path / "report.sarif.json"
    junit = tmp_path / "report.xml"
    write_events(baseline_source)
    write_events(candidate_source, status="error", tool="delete_file")
    capture(baseline_source, baseline)
    capture(candidate_source, candidate)

    comparison = runner.invoke(app, ["compare", str(baseline), str(candidate), "--json"])
    assert comparison.exit_code == 4
    assert "TOOL_CHANGED" in comparison.output
    assert "RUN_STATUS_CHANGED" in comparison.output

    sarif_result = runner.invoke(
        app,
        [
            "report",
            str(baseline),
            str(candidate),
            "--format",
            "sarif",
            "--output",
            str(sarif),
        ],
    )
    assert sarif_result.exit_code == 4
    assert json.loads(sarif.read_text(encoding="utf-8"))["version"] == "2.1.0"

    junit_result = runner.invoke(
        app,
        [
            "report",
            str(baseline),
            str(candidate),
            "--format",
            "junit",
            "--output",
            str(junit),
        ],
    )
    assert junit_result.exit_code == 4
    assert "testsuite" in junit.read_text(encoding="utf-8")


def test_report_rejects_unknown_format(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    write_events(source)
    capture(source, artifact)
    result = runner.invoke(
        app,
        ["report", str(artifact), str(artifact), "--format", "yaml"],
    )
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.output
