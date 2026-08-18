"""Tests closing the remaining coverage gaps identified in the coverage report.

Covered gaps (relative to main baseline):
- ``vouchline.__main__`` entry point (0% branch coverage)
- ``canonical.jsonable`` date serialization branch
- ``capture.write_artifact`` unwritable-target path
- ``cli`` error formatting, compare/report/replay failure paths, ``main()``
- ``comparison`` event-count change finding and non-string payload filtering
- ``replay`` reused call_id rejection
- ``adapters.otlp_json`` non-dict attribute value handling
- ``reporting`` JUnit warning-severity mapping
"""

from __future__ import annotations

import json
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from vouchline import __main__
from vouchline.canonical import jsonable
from vouchline.capture import build_artifact, load_artifact, parse_jsonl, write_artifact
from vouchline.cli import app, main
from vouchline.comparison import compare_artifacts
from vouchline.errors import InputError, ReplayError
from vouchline.models import Producer
from vouchline.replay import replay_artifact

runner = CliRunner()

PRODUCER = Producer(name="tester", version="1")


def _rec(
    sequence: int,
    kind: str,
    actor: str,
    payload: dict[str, object] | None = None,
    call_id: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "sequence": sequence,
        "event_id": str(sequence),
        "kind": kind,
        "actor": actor,
    }
    if payload is not None:
        record["payload"] = payload
    if call_id is not None:
        record["call_id"] = call_id
    return record


def _events_jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(record) for record in records) + "\n"


_build_counter = 0


def _build_artifact(records: list[dict[str, object]], artifact_id: str | None = None) -> object:
    """Build a real artifact so hashes and the digest chain are valid."""
    global _build_counter
    _build_counter += 1
    with_timestamps = [
        dict(record, timestamp="2026-01-01T00:00:00Z") if "timestamp" not in record else record
        for record in records
    ]
    events, _ = parse_jsonl(StringIO(_events_jsonl(with_timestamps)))
    return build_artifact(
        events,
        run_id="run-1",
        producer=PRODUCER,
        redaction_count=0,
        artifact_id=artifact_id or f"art-{_build_counter}",
    )


def _write_artifact(
    tmp_path: Path, name: str, records: list[dict[str, object]], artifact_id: str | None = None
) -> Path:
    path = tmp_path / name
    write_artifact(path, _build_artifact(records, artifact_id=artifact_id))
    return path


# ---------------------------------------------------------------- canonical
def test_jsonable_serializes_standalone_date() -> None:
    """The ``date`` branch in ``jsonable`` was previously untested."""
    assert jsonable(date(2026, 8, 18)) == "2026-08-18"


def test_jsonable_passthrough_for_plain_types() -> None:
    """Non-model, non-datetime values return unchanged."""
    assert jsonable("literal") == "literal"
    assert jsonable(42) == 42


# -------------------------------------------------------------------- capture
def test_write_artifact_raises_on_unwritable_target(tmp_path: Path) -> None:
    """``write_artifact`` must surface an ``InputError`` for write failures."""
    from vouchline.capture import write_artifact

    artifact = _build_artifact(
        [
            {"sequence": i, "event_id": str(i), "kind": "run.started", "actor": "agent"}
            for i in range(1, 4)
        ],
        artifact_id="write-test",
    )
    target = tmp_path / "dir" / "artifact.json"
    # Point the artifact path at an existing directory: write_bytes raises OSError.
    target.mkdir(parents=True)
    with pytest.raises(InputError) as exc_info:
        write_artifact(target, artifact)
    assert exc_info.value.code == "INVALID_INPUT"
    assert exc_info.value.details.get("reason") == "write_failed"


# ----------------------------------------------------------------------- cli
def test_cli_unexpected_error_omits_details_section(tmp_path: Path) -> None:
    """The ``_unexpected`` branch never prints a details section."""
    source = tmp_path / "events.jsonl"
    source.write_text("[]\n", encoding="utf-8")

    def explode() -> object:
        raise OSError("simulated internal failure")

    with mock.patch("vouchline.cli.parse_jsonl", side_effect=explode):
        result = runner.invoke(
            app,
            ["capture", str(source), "--output", str(tmp_path / "out.json"), "--run-id", "r"],
        )
    assert result.exit_code == 5
    assert "INTERNAL_ERROR" in result.output
    assert "Details:" not in result.output


def test_cli_unexpected_error_in_json_mode(tmp_path: Path) -> None:
    """The ``_unexpected`` JSON path for failures outside ``VouchlineError``."""
    source = tmp_path / "events.jsonl"
    source.write_text("[]\n", encoding="utf-8")

    def explode() -> object:
        raise TypeError("simulated internal failure")

    with mock.patch("vouchline.cli.parse_jsonl", side_effect=explode):
        result = runner.invoke(
            app,
            [
                "capture",
                str(source),
                "--output",
                str(tmp_path / "out.json"),
                "--run-id",
                "r",
                "--json",
            ],
        )
    assert result.exit_code == 5
    error = json.loads(result.output.splitlines()[0])["error"]
    assert error["code"] == "INTERNAL_ERROR"


def test_cli_unexpected_error_in_human_mode(tmp_path: Path) -> None:
    """The ``_unexpected`` human-readable path prints the internal banner."""
    source = tmp_path / "events.jsonl"
    source.write_text("[]\n", encoding="utf-8")

    def explode() -> object:
        raise OSError("simulated internal failure")

    with mock.patch("vouchline.cli.parse_jsonl", side_effect=explode):
        result = runner.invoke(
            app,
            ["capture", str(source), "--output", str(tmp_path / "out.json"), "--run-id", "r"],
        )
    assert result.exit_code == 5
    assert "INTERNAL_ERROR" in result.output
    assert "Details:" not in result.output


def test_cli_compare_failure_prints_findings_and_exits_four(tmp_path: Path) -> None:
    """The ``compare`` failure rendering and exit-code-4 paths."""
    baseline_path = _write_artifact(
        tmp_path,
        "baseline.json",
        [
            _rec(1, "tool.requested", "agent", payload={"tool": "search"}, call_id="c1"),
            _rec(2, "tool.responded", "search", payload={"status": "ok"}, call_id="c1"),
        ],
    )
    candidate_path = _write_artifact(
        tmp_path,
        "candidate.json",
        [
            _rec(1, "tool.requested", "agent", payload={"tool": "fetch"}, call_id="c1"),
            _rec(2, "tool.responded", "fetch", payload={"status": "error"}, call_id="c1"),
        ],
    )

    result = runner.invoke(app, ["compare", str(baseline_path), str(candidate_path)])
    assert result.exit_code == 4
    assert "TOOL_CHANGED" in result.output


def test_cli_report_writes_output_file(tmp_path: Path) -> None:
    """The ``report --output`` branch that persists the rendered report."""
    events = [
        _rec(1, "run.started", "agent"),
        _rec(2, "run.finished", "agent", payload={"status": "ok"}),
    ]
    left = _write_artifact(tmp_path, "left.json", events)
    right = _write_artifact(tmp_path, "right.json", events)

    report_path = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "report",
            str(left),
            str(right),
            "--format",
            "sarif",
            "--output",
            str(report_path),
        ],
    )
    assert result.exit_code == 0
    assert report_path.read_text(encoding="utf-8").startswith('{"$schema"')


def test_cli_report_invalid_format_error_path(tmp_path: Path) -> None:
    """The ``report`` branch raising ``InputError`` for an unknown format."""
    events = [_rec(1, "run.started", "agent")]
    left = _write_artifact(tmp_path, "left.json", events)
    right = _write_artifact(tmp_path, "right.json", events)

    result = runner.invoke(app, ["report", str(left), str(right), "--format", "markdown"])
    assert result.exit_code == 2
    assert "format must be one of json, sarif, or junit" in result.output


def test_cli_replay_missing_responses_failure(tmp_path: Path) -> None:
    """The ``replay`` branch reporting an incomplete simulation."""
    events = [
        _rec(1, "tool.requested", "agent", payload={"tool": "search"}, call_id="c1"),
        # No matching ``tool.responded`` event: replay must fail deterministically.
    ]
    path = _write_artifact(tmp_path, "artifact.json", events)

    result = runner.invoke(app, ["replay", str(path), "--json"])
    assert result.exit_code == 4
    error = json.loads(result.output.splitlines()[0])["error"]
    assert error["code"] == "REPLAY_FAILURE"
    assert "missing_responses" in str(error.get("details"))


def test_cli_version_and_main_entry() -> None:
    """The ``version`` command and the ``__main__`` entry point."""
    assert runner.invoke(app, ["version"]).exit_code == 0

    with mock.patch("vouchline.cli.app") as app_mock:
        main()
        app_mock.assert_called_once()


def test_main_module_runs_app() -> None:
    """``python -m vouchline`` delegates to ``cli.main``."""
    with mock.patch("vouchline.__main__.main") as main_mock:
        __main__.main()
        main_mock.assert_called_once()


# ----------------------------------------------------------------- comparison
def _load(path: Path) -> object:
    return load_artifact(path)


def test_comparison_filters_non_string_tool_and_status(tmp_path: Path) -> None:
    """The branches filtering non-string ``tool`` and ``status`` values."""
    baseline = _load(
        _write_artifact(
            # ``tool.requested`` with a non-string ``tool`` and
            # ``tool.responded`` with a non-string ``status`` must be ignored.
            tmp_path,
            "baseline.json",
            [
                _rec(1, "tool.requested", "agent", payload={"tool": 123}, call_id="c1"),
                _rec(2, "tool.responded", "agent", payload={"status": None}, call_id="c1"),
            ],
        )
    )
    candidate = _load(
        _write_artifact(
            tmp_path,
            "candidate.json",
            [
                _rec(1, "tool.requested", "agent", payload={"tool": True}, call_id="c1"),
                _rec(2, "tool.responded", "agent", payload={"status": {"nested": 1}}, call_id="c1"),
            ],
        )
    )
    report = compare_artifacts(baseline, candidate)
    assert report.passed
    assert not report.findings


def test_comparison_detects_event_count_change(tmp_path: Path) -> None:
    """The ``EVENT_COUNT_CHANGED`` finding was previously untested."""
    baseline = _load(
        _write_artifact(
            tmp_path,
            "baseline.json",
            [_rec(1, "run.started", "agent")],
        )
    )
    candidate = _load(
        _write_artifact(
            tmp_path,
            "candidate.json",
            [
                _rec(1, "run.started", "agent"),
                _rec(2, "run.started", "agent"),
            ],
        )
    )
    report = compare_artifacts(baseline, candidate)
    codes = [finding.code for finding in report.findings]
    assert "EVENT_COUNT_CHANGED" in codes


# --------------------------------------------------------------------- replay
def test_replay_rejects_reused_call_id_before_response(tmp_path: Path) -> None:
    """The ``call_id`` reuse branch in ``replay_artifact``."""
    path = _write_artifact(
        tmp_path,
        "artifact.json",
        [
            _rec(1, "tool.requested", "agent", payload={"tool": "search"}, call_id="c1"),
            _rec(2, "tool.requested", "agent", payload={"tool": "fetch"}, call_id="c1"),
            _rec(3, "tool.responded", "search", payload={"status": "ok"}, call_id="c1"),
        ],
    )
    with pytest.raises(ReplayError) as exc_info:
        replay_artifact(load_artifact(path))
    assert exc_info.value.details.get("call_id") == "c1"
    assert exc_info.value.code == "REPLAY_FAILURE"


# ----------------------------------------------------------- adapters/otlp
def test_otlp_attribute_with_non_dict_value_is_skipped() -> None:
    """The branch skipping attribute items whose ``value`` is not a mapping."""
    from vouchline.adapters.otlp_json import spans_to_events

    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "name": "extension.activity",
                                "spanId": "s1",
                                "startTimeUnixNano": "1723939200000000000",
                                "attributes": [{"key": "detail", "value": "scalar-string"}],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    events = spans_to_events(payload)
    # The attribute could not be flattened (value is not a mapping), so the
    # extension span carries an empty attributes payload.
    assert events
    assert events[0]["payload"]["attributes"] == {}


# --------------------------------------------------------------- reporting
def test_reporting_junit_warning_status_attribute() -> None:
    """The JUnit branch setting ``status`` for non-error findings."""
    from vouchline.comparison import ComparisonFinding
    from vouchline.models import ComparisonReport
    from vouchline.reporting import comparison_junit

    report = ComparisonReport(
        passed=False,
        baseline_artifact_id="b",
        candidate_artifact_id="c",
        findings=[
            ComparisonFinding(
                code="TOOL_OUTCOME_CHANGED",
                message="outcome drifted",
                severity="warning",
                call_id="c1",
            )
        ],
    )
    junit = comparison_junit(report)
    assert 'status="warning"' in junit
    assert "<failure" not in junit


# -------------------------------------------------------------- __main__
def test_main_entry_script_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executing the package as ``python -m vouchline`` must invoke ``main``."""
    import runpy

    monkeypatch.setattr("sys.argv", ["vouchline", "version"])
    with mock.patch("vouchline.cli.main") as main_mock:
        runpy.run_module("vouchline.__main__", run_name="__main__", alter_sys=True)
        main_mock.assert_called()
