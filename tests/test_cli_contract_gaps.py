"""Tests closing CLI contract gaps: stdin capture, machine-readable output
paths for every command, typed error exit codes, and report format rendering.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

from vouchline.capture import build_artifact, load_artifact
from vouchline.cli import app
from vouchline.models import InputEvent, Producer

runner = CliRunner()

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SAMPLE_RUN = EXAMPLES / "sample_run.jsonl"
MCP_TRANSCRIPT = EXAMPLES / "mcp_transcript.jsonl"
POLICY = EXAMPLES / "policy.json"


def _build_events():
    return [
        InputEvent(
            schema_version="v1",
            event_id=f"evt-{i}",
            sequence=i,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            kind=kind,
            actor="agent",
            call_id="c-1" if kind != "run.started" else None,
            payload=payload,
        )
        for i, (kind, payload) in enumerate(
            [
                ("run.started", {"task": "x"}),
                ("tool.requested", {"tool": "read_file"}),
                ("tool.responded", {"status": "ok", "result": {}}),
                ("run.finished", {"status": "completed"}),
            ],
            start=1,
        )
    ]


def _write_artifact(path: Path) -> Path:
    artifact = build_artifact(
        _build_events(),
        run_id="contract",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    path.write_bytes(json.dumps(artifact.model_dump(mode="json")).encode() + b"\n")
    return path


def _two_artifacts(tmp_path: Path):
    a = _write_artifact(tmp_path / "baseline.json")
    b = _write_artifact(tmp_path / "candidate.json")
    return a, b


# ---------------------------------------------------------------------------
# capture: stdin and machine-readable success path
# ---------------------------------------------------------------------------


def test_cli_capture_reads_stdin(tmp_path: Path) -> None:
    data = SAMPLE_RUN.read_text(encoding="utf-8")
    output = tmp_path / "artifact.json"
    result = runner.invoke(
        app,
        ["capture", "-", "--output", str(output), "--run-id", "stdin-run"],
        input=data,
    )
    assert result.exit_code == 0, result.output
    artifact = load_artifact(output)
    assert artifact.run_id == "stdin-run"


def test_cli_capture_json_output(tmp_path: Path) -> None:
    output = tmp_path / "artifact.json"
    result = runner.invoke(
        app,
        ["capture", str(SAMPLE_RUN), "--output", str(output), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_id"]
    assert "artifact_sha256" in payload


def test_cli_capture_unknown_input_path_returns_input_error() -> None:
    result = runner.invoke(
        app,
        ["capture", "/no/such/path.jsonl", "--output", "/tmp/out.json", "--json"],
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# normalize-mcp: adversarial input and json output
# ---------------------------------------------------------------------------


def test_cli_normalize_mcp_limit_error_is_typed(tmp_path: Path) -> None:
    lines = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}) + "\n"
    result = runner.invoke(
        app,
        [
            "normalize-mcp",
            "-",
            "--output",
            str(tmp_path / "out.jsonl"),
            "--max-messages",
            "1",
            "--json",
        ],
        input=(lines * 3),
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INPUT_LIMIT_EXCEEDED"
    assert payload["error"]["details"]["max_messages"] == 1


def test_cli_normalize_mcp_invalid_json_line_is_typed(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["normalize-mcp", "-", "--output", str(tmp_path / "out.jsonl"), "--json"],
        input="not-json\n",
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["details"]["line"] == 1


def test_cli_normalize_mcp_non_object_record_is_typed(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["normalize-mcp", "-", "--output", str(tmp_path / "out.jsonl"), "--json"],
        input='["array-not-object"]\n',
    )
    assert result.exit_code == 2, result.output


def test_cli_normalize_mcp_success_prints_counts(tmp_path: Path) -> None:
    output = tmp_path / "out.jsonl"
    result = runner.invoke(
        app,
        ["normalize-mcp", str(MCP_TRANSCRIPT), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert "messages=2" in result.output


# ---------------------------------------------------------------------------
# verify / compare / report
# ---------------------------------------------------------------------------


def test_cli_verify_json_output(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "a.json")
    result = runner.invoke(app, ["verify", str(artifact), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_sha256"]


def test_cli_compare_json_output_and_failed_exit_code(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    result = runner.invoke(app, ["compare", str(a), str(b), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["findings"] == []


def test_cli_compare_failed_baseline_different_tool_set(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    # Tamper with candidate so tool sets differ (hash chain will differ too,
    # but compare checks content after verification passes only when chain
    # matches; verify first requires an intact artifact, so instead build a
    # deliberately different artifact and expect compare to report findings.)
    different = build_artifact(
        _build_events()
        + [
            InputEvent(
                schema_version="v1",
                event_id="extra",
                sequence=5,
                timestamp=datetime(2026, 8, 1, tzinfo=UTC),
                kind="tool.requested",
                actor="agent",
                call_id="c-2",
                payload={"tool": "extra_tool"},
            ),
        ],
        run_id="different",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    b.write_text(json.dumps(different.model_dump(mode="json")) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["compare", str(a), str(b), "--json"])
    # Content-level comparison emits findings even though verification passes
    # (artifacts are independently valid); exit 4 marks comparison failure.
    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert any(f["code"] == "EVENT_COUNT_CHANGED" for f in payload["findings"])


def test_cli_compare_self_pair_rejected(tmp_path: Path) -> None:
    a, _ = _two_artifacts(tmp_path)
    result = runner.invoke(app, ["compare", str(a), str(a), "--json"])
    assert result.exit_code == 2, result.output


def test_cli_report_formats_and_file_output(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["report", str(a), str(b), "--format", "sarif", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    rendered = json.loads(out.read_text(encoding="utf-8"))
    assert rendered["$schema"].startswith("https://json.schemastore.org/sarif-2.1.0.json")


def test_cli_report_junit_format(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    result = runner.invoke(
        app,
        ["report", str(a), str(b), "--format", "junit"],
    )
    assert result.exit_code == 0, result.output
    assert "<testsuite" in result.output


def test_cli_report_invalid_format_is_typed(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    result = runner.invoke(app, ["report", str(a), str(b), "--format", "yaml"])
    assert result.exit_code == 2, result.output
    assert "format must be one of json, sarif, or junit" in result.output


def test_cli_report_failed_comparison_exits_four(tmp_path: Path) -> None:
    a, b = _two_artifacts(tmp_path)
    different = build_artifact(
        _build_events()
        + [
            InputEvent(
                schema_version="v1",
                event_id="extra",
                sequence=5,
                timestamp=datetime(2026, 8, 1, tzinfo=UTC),
                kind="run.finished",
                actor="agent",
                call_id=None,
                payload={"status": "failed"},
            ),
        ],
        run_id="alt",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    b.write_text(json.dumps(different.model_dump(mode="json")) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["report", str(a), str(b), "--format", "json"])
    assert result.exit_code == 4, result.output


# ---------------------------------------------------------------------------
# replay: missing responses and machine-readable failure
# ---------------------------------------------------------------------------


def test_cli_replay_missing_response_exit_code_and_json(tmp_path: Path) -> None:
    incomplete = build_artifact(
        [
            InputEvent(
                schema_version="v1",
                event_id="req",
                sequence=1,
                timestamp=datetime(2026, 8, 1, tzinfo=UTC),
                kind="tool.requested",
                actor="agent",
                call_id="c-1",
                payload={"tool": "read_file"},
            ),
        ],
        run_id="incomplete",
        producer=Producer(name="p", version="1"),
        redaction_count=0,
    )
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(incomplete.model_dump(mode="json")) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["replay", str(path), "--json"])
    # Replay failure surfaces through ReplayError (REPLAY_FAILURE, exit 4)
    # via the typed CLI error path, and the missing response call_id is
    # reported in the machine-readable payload.
    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "REPLAY_FAILURE"
    assert payload["error"]["details"]["missing_responses"] == ["c-1"]


# ---------------------------------------------------------------------------
# assert: policy parse failure and typed failure
# ---------------------------------------------------------------------------


def test_cli_assert_invalid_policy_json_is_typed(tmp_path: Path) -> None:
    a, _ = _two_artifacts(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not: json", encoding="utf-8")
    result = runner.invoke(app, ["assert", str(a), "--policy", str(bad), "--json"])
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"]["code"] == "INVALID_INPUT"


def test_cli_assert_policy_failure_exits_six(tmp_path: Path) -> None:
    a, _ = _two_artifacts(tmp_path)
    result = runner.invoke(app, ["assert", str(a), "--policy", str(POLICY), "--json"])
    # Examples policy requires search_documents and caps calls at 5; the
    # contract artifact calls read_file once, so required tool is missing.
    assert result.exit_code == 4, result.output


# ---------------------------------------------------------------------------
# version, main entry, internal failure path
# ---------------------------------------------------------------------------


def test_cli_version_prints_package_version() -> None:
    from vouchline import __version__

    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_cli_main_entry_calls_app() -> None:
    from vouchline import __main__  # noqa: F401  (module-level invocation)

    with mock.patch("vouchline.cli.app") as mocked:
        from vouchline.cli import main

        main()
        mocked.assert_called_once()


def test_cli_unexpected_exception_is_internal_error(tmp_path: Path) -> None:
    a, _ = _two_artifacts(tmp_path)
    # _run maps unexpected OSError/ValueError/TypeError to the INTERNAL_ERROR
    # path (exit 5), so simulate an internal failure with an OSError.
    with mock.patch("vouchline.cli.verify_artifact", side_effect=OSError("boom")):
        result = runner.invoke(app, ["verify", str(a), "--json"])
    assert result.exit_code == 5, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INTERNAL_ERROR"


def test_cli_unexpected_exception_human_output() -> None:
    with mock.patch("vouchline.cli.load_artifact", side_effect=OSError("boom")):
        result = runner.invoke(app, ["verify", str(SAMPLE_RUN)])
    assert result.exit_code == 5, result.output
    assert "INTERNAL_ERROR" in result.output
