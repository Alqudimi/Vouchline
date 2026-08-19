# Development Guide

## Local installation

Use Python 3.11 or newer and install the project with development extras:

```bash
python -m pip install -e '.[dev]'
```

The package exposes both `vouchline` and `python -m vouchline` entry points. No API key, model provider, database, or external service is required for the MVP.

## Configuration

The CLI takes configuration through explicit flags and JSON policy files. There is no implicit `.env` loading and no secret lookup in the core. `capture` accepts `--max-events` and `--max-bytes` limits; `normalize-mcp` accepts `--max-messages` and `--max-bytes` limits. `assert` accepts a JSON file with `deny_tools`, `max_tool_calls`, `require_tools`, and `deny_statuses`.

A future server or adapter may add environment configuration, but it must preserve secure defaults and document precedence explicitly.

## Library API

The stable public imports are exported from `vouchline`:

```python
from pathlib import Path

from vouchline import (
    Producer,
    build_artifact,
    evaluate_policy,
    load_artifact,
    parse_jsonl,
    replay_artifact,
    verify_artifact,
)
```

Use `parse_jsonl` at an input boundary, `build_artifact` to create a versioned artifact, `verify_artifact` before consuming an artifact, and `replay_artifact` for simulation. `evaluate_policy` is deterministic and returns structured findings rather than throwing for a normal policy violation. Typed exceptions signal invalid input, integrity failure, replay failure, and policy failure.

## Adding an adapter

An adapter should live outside the domain modules and translate an external event source into `InputEvent` objects. It must validate external payloads, retain the source format/version in producer metadata, redact before persistence, and provide offline fixtures. An adapter must not add network or process execution to `replay.py`.

The implemented MCP adapter in `vouchline.adapters.mcp_jsonl` maps offline JSON-RPC tool requests and results into the core `tool.requested` and `tool.responded` events, while preserving other messages as `extension.mcp.message`. The `normalize-mcp` CLI command enforces message and UTF-8 byte limits before writing normalized JSONL. The OTLP adapter maps span attributes into the same contract while preserving source IDs in the payload. Both adapters are pure transformations: they do not connect to servers, open sockets, execute processes, or bypass the normal capture redaction boundary.

## Testing

Run the full local gate:

```bash
pytest -q --cov=vouchline --cov-report=term-missing
ruff check src tests benchmarks
ruff format --check src tests benchmarks
mypy src
pip-audit --strict
python -m build
```

Tests must not rely on network access or real credentials. Security tests should assert both the intended behavior and the absence of leaked values in serialized artifacts.

## Docker

Build and inspect help:

```bash
docker build -t vouchline:local .
docker run --rm vouchline:local --help
```

To process a local artifact, mount a working directory and pass a path inside the container. The image has no server process and does not execute arbitrary input by default.

## Troubleshooting

If capture reports `INVALID_INPUT`, inspect the line number and confirm that every JSONL record is an object with `schema_version: "v1"`, contiguous `sequence` values, an RFC3339 timestamp, a known core kind or `extension.*`, and the required tool fields. If verify reports `INTEGRITY_FAILURE`, treat the artifact as untrusted; do not manually edit the manifest to make it pass.

If replay reports missing responses, add a matching `tool.responded` event with the same `call_id` to the source capture. A response without a request is rejected because silently accepting it would make the evidence ambiguous. If a policy fails, use `--json` to inspect the finding count and run-specific diagnostics, then decide whether the policy or the producer behavior should change.
