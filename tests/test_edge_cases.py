from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from vouchline.canonical import canonical_bytes
from vouchline.capture import build_artifact, load_artifact, parse_jsonl, write_artifact
from vouchline.cli import _run, app
from vouchline.errors import InputError, IntegrityError, PolicyError, ReplayError
from vouchline.integrity import verify_artifact
from vouchline.models import InputEvent, Policy, Producer
from vouchline.policy import evaluate_policy
from vouchline.replay import replay_artifact

runner = CliRunner()


def make_event(
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
        actor="edge-test",
        call_id=call_id,
        payload=payload,
    )


def make_artifact() -> object:
    events = [
        make_event(1, "run.started", {}),
        make_event(2, "tool.requested", {"tool": "search"}, "call-1"),
        make_event(3, "tool.responded", {"status": "ok"}, "call-1"),
        make_event(4, "run.finished", {"status": "completed"}),
    ]
    return build_artifact(
        events,
        run_id="edge",
        producer=Producer(name="test", version="1"),
        redaction_count=0,
        artifact_id="artifact-edge",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_canonical_handles_models_and_dates() -> None:
    payload = canonical_bytes({"when": datetime(2026, 1, 1, tzinfo=UTC), "value": 1})
    assert b"2026-01-01T00:00:00+00:00" in payload


def test_capture_rejects_bad_json_non_object_and_empty() -> None:
    with pytest.raises(InputError, match="invalid JSON"):
        parse_jsonl(io.StringIO("not-json\n"))
    with pytest.raises(InputError, match="object"):
        parse_jsonl(io.StringIO("[]\n"))
    with pytest.raises(InputError, match="no events"):
        parse_jsonl(io.StringIO("\n"))


def test_capture_enforces_event_limit_and_build_rejects_empty() -> None:
    raw = {
        "schema_version": "v1",
        "event_id": "1",
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "kind": "run.started",
        "actor": "agent",
        "payload": {},
    }
    with pytest.raises(InputError, match="event limit"):
        parse_jsonl(io.StringIO(json.dumps(raw) + "\n"), max_events=0)
    with pytest.raises(InputError, match="without events"):
        build_artifact(
            [], run_id="empty", producer=Producer(name="x", version="1"), redaction_count=0
        )


def test_artifact_load_write_and_schema_errors(tmp_path: Path) -> None:
    artifact = make_artifact()
    path = tmp_path / "artifact.json"
    write_artifact(path, artifact)
    assert load_artifact(path).artifact_id == "artifact-edge"
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("not-json", encoding="utf-8")
    with pytest.raises(InputError, match="could not be read"):
        load_artifact(invalid_json)
    invalid_schema = tmp_path / "schema.json"
    invalid_schema.write_text("{}", encoding="utf-8")
    with pytest.raises(InputError, match="schema"):
        load_artifact(invalid_schema)


def test_integrity_rejects_each_manifest_failure() -> None:
    artifact = make_artifact()
    base = artifact.model_dump(mode="json")
    cases = [
        ({"events": [{"sequence": 9}]}, "sequence"),
        ({"events": [{"previous_hash": "f" * 64}]}, "chain"),
        ({"manifest": {"event_count": 9}}, "event count"),
        ({"manifest": {"first_hash": "f" * 64}}, "first_hash"),
        ({"manifest": {"last_hash": "f" * 64}}, "last_hash"),
        ({"manifest": {"artifact_sha256": "f" * 64}}, "artifact digest"),
    ]
    for update, message in cases:
        candidate = json.loads(json.dumps(base))
        if "events" in update:
            candidate["events"][0].update(update["events"][0])
        else:
            candidate["manifest"].update(update["manifest"])
        tampered = artifact.__class__.model_validate(candidate)
        with pytest.raises(IntegrityError, match=message):
            verify_artifact(tampered)


def test_replay_and_policy_validate_required_payload_fields() -> None:
    missing_request_id = build_artifact(
        [make_event(1, "tool.requested", {"tool": "search"})],
        run_id="r",
        producer=Producer(name="x", version="1"),
        redaction_count=0,
    )
    with pytest.raises(ReplayError, match="no call_id"):
        replay_artifact(missing_request_id)

    missing_tool = build_artifact(
        [make_event(1, "tool.requested", {}, "call")],
        run_id="r",
        producer=Producer(name="x", version="1"),
        redaction_count=0,
    )
    with pytest.raises(ReplayError, match="valid field"):
        replay_artifact(missing_tool)

    missing_status = build_artifact(
        [make_event(1, "tool.responded", {}, "call")],
        run_id="r",
        producer=Producer(name="x", version="1"),
        redaction_count=0,
    )
    with pytest.raises(ReplayError, match="no matching"):
        replay_artifact(missing_status)

    with pytest.raises(PolicyError, match="tool name"):
        evaluate_policy(missing_tool, Policy())
    with pytest.raises(PolicyError, match="status"):
        evaluate_policy(missing_status, Policy())


def test_cli_human_output_stdin_and_version(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    row = {
        "schema_version": "v1",
        "event_id": "1",
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "kind": "run.started",
        "actor": "agent",
        "payload": {},
    }
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    artifact = tmp_path / "artifact.json"
    captured = runner.invoke(app, ["capture", str(source), "--output", str(artifact)])
    assert captured.exit_code == 0
    assert "Vouchline capture" in captured.stdout
    assert runner.invoke(app, ["verify", str(artifact)]).exit_code == 0
    assert runner.invoke(app, ["replay", str(artifact)]).exit_code == 0
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    assert runner.invoke(app, ["assert", str(artifact), "--policy", str(policy)]).exit_code == 0
    stdin_artifact = tmp_path / "stdin.json"
    stdin_result = runner.invoke(
        app,
        ["capture", "-", "--output", str(stdin_artifact)],
        input=json.dumps(row) + "\n",
    )
    assert stdin_result.exit_code == 0
    assert runner.invoke(app, ["version"]).exit_code == 0


def test_cli_expected_errors_and_unexpected_mapping(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["verify", str(tmp_path / "missing.json")])
    assert missing.exit_code != 0
    bad_policy = tmp_path / "bad-policy.json"
    bad_policy.write_text("not-json", encoding="utf-8")
    artifact_path = tmp_path / "artifact.json"
    write_artifact(artifact_path, make_artifact())
    result = runner.invoke(app, ["assert", str(artifact_path), "--policy", str(bad_policy)])
    assert result.exit_code == 2
    assert "INVALID_INPUT" in result.stdout
    with pytest.raises(typer.Exit):
        _run(lambda: int("not-an-int"), False)
