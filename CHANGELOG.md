# Changelog

All notable changes to Vouchline are documented here.

## [0.3.2] — 2026-08-20

### Fixed

- Classify an MCP JSON-RPC response as `tool.responded` only when a matching `tools/call` request is pending.
- Preserve unrelated responses such as `initialize` and `tools/list` as `extension.mcp.message` events.
- Add regression coverage for generic responses and error responses.

## [0.3.1] — 2026-08-19

### Fixed

- Enforce a UTF-8 byte limit in the `normalize-mcp` CLI before materializing transcript messages.
- Document the implemented MCP/OTLP adapters and their redaction boundary accurately.

## [0.3.0] — 2026-08-18

### Added

- Pure MCP JSON-RPC transcript normalization into the Vouchline event contract.
- `vouchline normalize-mcp INPUT --output EVENTS.jsonl` for local and CI pipelines.
- Bounded MCP message handling, invalid-record diagnostics, and regression coverage for requests, results, errors, notifications, and CLI failures.
- Public `messages_to_events` export for library integrations.

### Boundaries

- The MCP adapter reads already-captured JSONL; it never connects to an MCP server or executes a tool.
- Redaction and integrity remain owned by the normal capture path after normalization.
- SQLite indexing, detached attestations, and hosted services remain future extensions.

## [0.2.2] — 2026-08-18

### Fixed

- Use SPDX `MIT` and `license-files` metadata so isolated builds avoid deprecated setuptools license configuration warnings.

## [0.2.1] — 2026-08-17

### Fixed

- Map informational comparison findings to SARIF `note`, which is a valid SARIF level, and add a regression test for the mapping.
- Keep package metadata and the public `__version__` synchronized at `0.2.1`.

## [0.2.0] — 2026-08-16

### Added

- Deterministic baseline comparison for verified artifacts, including tool, outcome, event-count, and run-status regressions.
- JSON, SARIF 2.1.0, and JUnit XML report renderers for CI integrations.
- Pure OTLP/JSON span normalization adapter for GenAI/MCP-style tool spans, with bounded input handling and no network access.
- Public Python exports for comparison and OTLP normalization.
- Regression tests for comparison failures, report formats, malformed input, and adapter behavior.

### Boundaries

- MCP and OTLP **network receivers** are not part of `0.2.0`; OTLP support is a pure JSON transformation adapter.
- Replay is simulation-only; live execution is not implemented.
- Hash chains are not signatures or producer authentication.
- SQLite indexing, detached signatures, and hosted services remain future extensions.

## [0.1.0] — 2026-08-16

### Added

- Versioned `InputEvent` and `Artifact` contracts.
- JSONL capture with bounded input limits and conservative pre-persistence redaction.
- SHA-256 event hash chain and artifact manifest verification.
- Side-effect-free replay of recorded tool requests and responses.
- Deterministic policy assertions for denied tools, required tools, call budgets, and denied statuses.
- Human-readable and JSON CLI output with stable exit codes.
- Python package metadata, Dockerfile, Makefile, examples, benchmarks, tests, and contributor/security governance files.

### Known boundaries

- Replay is simulation-only; live execution is not implemented.
- Hash chains are not signatures or producer authentication.
- There is no server, database, web UI, or hosted registry in this release.
