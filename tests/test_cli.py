from __future__ import annotations

import json
from pathlib import Path

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
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_cli_lifecycle(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    policy = tmp_path / "policy.json"
    write_sample(source)
    policy.write_text('{"require_tools":["search"],"max_tool_calls":1}', encoding="utf-8")

    captured = runner.invoke(
        app,
        ["capture", str(source), "--output", str(artifact), "--json"],
    )
    assert captured.exit_code == 0, captured.stdout
    assert json.loads(captured.stdout)["event_count"] == 3

    verified = runner.invoke(app, ["verify", str(artifact), "--json"])
    assert verified.exit_code == 0
    assert json.loads(verified.stdout)["valid"] is True

    replayed = runner.invoke(app, ["replay", str(artifact), "--json"])
    assert replayed.exit_code == 0
    assert json.loads(replayed.stdout)["simulated"] is True

    asserted = runner.invoke(
        app,
        ["assert", str(artifact), "--policy", str(policy), "--json"],
    )
    assert asserted.exit_code == 0
    assert json.loads(asserted.stdout)["passed"] is True


def test_cli_policy_failure_has_machine_code(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    artifact = tmp_path / "artifact.json"
    policy = tmp_path / "policy.json"
    write_sample(source)
    policy.write_text('{"deny_tools":["search"]}', encoding="utf-8")
    assert runner.invoke(app, ["capture", str(source), "--output", str(artifact)]).exit_code == 0

    result = runner.invoke(app, ["assert", str(artifact), "--policy", str(policy), "--json"])
    assert result.exit_code == 4
    assert "POLICY_FAILURE" in result.output
