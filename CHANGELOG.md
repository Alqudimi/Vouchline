# Changelog

All notable changes to Vouchline are documented here.

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

- MCP and OTLP import adapters are not part of `0.1.0`.
- Replay is simulation-only; live execution is not implemented.
- Hash chains are not signatures or producer authentication.
- There is no server, database, web UI, or hosted registry in this release.
