# Changelog

All notable changes to Vouchline are documented here.

## [0.3.0] — unreleased

### Added

- Pure MCP JSONL adapter that normalizes MCP JSON-RPC tool call and result notifications into the core `tool.requested` and `tool.responded` vocabulary, preserving unknown notifications as `extension.mcp.notification` events, with bounded row limits, validation failures with stable error codes, provenance metadata, and no network access.

### Boundaries

- The MCP adapter is a pure JSON transformation; MCP **network receivers** are not implemented. Captured rows are expected to be redacted before persistence by the standard capture path.

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
