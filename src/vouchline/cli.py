"""Command-line interface for Vouchline."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import typer
from rich.console import Console
from rich.table import Table

from .capture import build_artifact, load_artifact, parse_jsonl, write_artifact
from .comparison import compare_artifacts
from .errors import VouchlineError
from .integrity import verify_artifact
from .models import Policy, Producer
from .policy import evaluate_policy
from .replay import replay_artifact
from .reporting import comparison_json, comparison_junit, comparison_sarif

app = typer.Typer(
    name="vouchline",
    help="Capture, verify, replay, and assert portable AI tool-run evidence.",
    no_args_is_help=True,
)
console = Console()


def _json_dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _output(value: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(_json_dump(value))


def _error(error: VouchlineError, json_output: bool) -> None:
    payload = {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    }
    if json_output:
        typer.echo(_json_dump(payload), err=True)
    else:
        console.print(f"[red]Error {error.code}:[/red] {error.message}")
        if error.details:
            console.print(f"Details: {_json_dump(error.details)}")
    raise typer.Exit(code=error.exit_code)


def _unexpected(error: Exception, json_output: bool) -> None:
    payload = {"error": {"code": "INTERNAL_ERROR", "message": "unexpected internal failure"}}
    if json_output:
        typer.echo(_json_dump(payload), err=True)
    else:
        console.print("[red]Error INTERNAL_ERROR:[/red] unexpected internal failure")
    raise typer.Exit(code=5) from error


def _run(operation: Callable[[], Any], json_output: bool) -> Any:
    try:
        return operation()
    except VouchlineError as error:
        _error(error, json_output)
    except (OSError, ValueError, TypeError) as error:
        _unexpected(error, json_output)
    return None


def _open_input(path: str) -> tuple[TextIO, bool]:
    if path == "-":
        return sys.stdin, False
    try:
        return Path(path).open("r", encoding="utf-8"), True
    except OSError as error:
        from .errors import InputError

        raise InputError("input file could not be opened", details={"path": path}) from error


@app.command()
def capture(
    input_path: str = typer.Argument(..., metavar="INPUT", help="JSONL path, or '-' for stdin."),
    output: Path = typer.Option(..., "--output", "-o", help="Destination JSON artifact."),
    run_id: str = typer.Option(
        "local-run", "--run-id", help="Stable identity for the recorded run."
    ),
    producer_name: str = typer.Option("vouchline", "--producer", help="Producer name."),
    producer_version: str = typer.Option("0.1.0", "--producer-version", help="Producer version."),
    max_events: int = typer.Option(100_000, min=1, help="Maximum non-empty JSONL records."),
    max_bytes: int = typer.Option(25 * 1024 * 1024, min=1, help="Maximum UTF-8 input bytes."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    def operation() -> Any:
        stream, should_close = _open_input(input_path)
        try:
            events, redaction_count = parse_jsonl(
                stream,
                max_events=max_events,
                max_bytes=max_bytes,
            )
        finally:
            if should_close:
                stream.close()
        artifact = build_artifact(
            events,
            run_id=run_id,
            producer=Producer(name=producer_name, version=producer_version),
            redaction_count=redaction_count,
        )
        write_artifact(output, artifact)
        return {
            "artifact": str(output),
            "artifact_id": artifact.artifact_id,
            "run_id": artifact.run_id,
            "event_count": len(artifact.events),
            "redacted_fields": redaction_count,
            "artifact_sha256": artifact.manifest.artifact_sha256,
        }

    result = _run(operation, json_output)
    if json_output:
        _output(result, True)
        return
    table = Table(title="Vouchline capture")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def verify(
    artifact: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    result = _run(lambda: verify_artifact(load_artifact(artifact)), json_output)
    if json_output:
        _output(result, True)
        return
    console.print(
        f"[green]Valid artifact.[/green] events={result.event_count} "
        f"sha256={result.artifact_sha256}"
    )


@app.command()
def compare(
    baseline: Path = typer.Argument(..., exists=True, readable=True),
    candidate: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    result = _run(
        lambda: compare_artifacts(load_artifact(baseline), load_artifact(candidate)),
        json_output,
    )
    if json_output:
        _output(result, True)
    else:
        console.print(
            f"[green]Comparison passed.[/green] findings={len(result.findings)}"
            if result.passed
            else f"[red]Comparison failed.[/red] findings={len(result.findings)}"
        )
        for finding in result.findings:
            console.print(f"  [{finding.severity}] {finding.code}: {finding.message}")
    if not result.passed:
        raise typer.Exit(code=4)


@app.command()
def report(
    baseline: Path = typer.Argument(..., exists=True, readable=True),
    candidate: Path = typer.Argument(..., exists=True, readable=True),
    format: str = typer.Option("json", "--format", help="json, sarif, or junit."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write report to a file."),
) -> None:
    def operation() -> tuple[object, bool]:
        result = compare_artifacts(load_artifact(baseline), load_artifact(candidate))
        normalized = format.lower()
        if normalized == "json":
            payload: object = comparison_json(result)
            rendered = _json_dump(payload)
        elif normalized == "sarif":
            payload = comparison_sarif(result, artifact_path=str(candidate))
            rendered = _json_dump(payload)
        elif normalized == "junit":
            payload = comparison_junit(result)
            rendered = payload
        else:
            from .errors import InputError

            raise InputError(
                "format must be one of json, sarif, or junit", details={"format": format}
            )
        if output is not None:
            output.write_text(rendered + "\n", encoding="utf-8")
        return rendered, result.passed

    rendered, passed = _run(operation, False)
    if output is None:
        typer.echo(rendered)
    if not passed:
        raise typer.Exit(code=4)


@app.command()
def replay(
    artifact: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    result = _run(lambda: replay_artifact(load_artifact(artifact)), json_output)
    if not result.passed:
        from .errors import ReplayError

        _error(
            ReplayError(
                "replay is incomplete because one or more tool responses are missing",
                details={"missing_responses": result.missing_responses},
            ),
            json_output,
        )
    if json_output:
        _output(result, True)
        return
    console.print(f"[green]Replay verified.[/green] simulated={result.simulated}")
    for step in result.steps:
        console.print(f"  #{step.sequence} {step.tool} -> {step.status}")


@app.command("assert")
def assert_policy(
    artifact: Path = typer.Argument(..., exists=True, readable=True),
    policy: Path = typer.Option(..., "--policy", "-p", exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    def operation() -> Any:
        try:
            raw_policy = json.loads(policy.read_text(encoding="utf-8"))
            parsed_policy = Policy.model_validate(raw_policy)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            from .errors import InputError

            raise InputError(
                "policy must be a valid JSON policy document",
                details={"path": str(policy), "reason": "policy_parse_error"},
            ) from error
        return evaluate_policy(load_artifact(artifact), parsed_policy)

    result = _run(operation, json_output)
    if not result.passed:
        from .errors import PolicyError

        _error(
            PolicyError(
                "policy assertions failed",
                details={"finding_count": len(result.findings)},
            ),
            json_output,
        )
    if json_output:
        _output(result, True)
        return
    console.print(f"[green]Policy passed.[/green] tool_calls={result.tool_call_count}")


@app.command()
def version() -> None:
    from . import __version__

    typer.echo(__version__)


def main() -> None:
    app()
