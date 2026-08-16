# Vouchline build checklist

- [x] Contract: typed event/artifact/policy/report models
- [x] Errors: stable exception hierarchy and exit codes
- [x] Canonical JSON and SHA-256 hash chain
- [x] Recursive redaction and leak guards
- [x] JSONL capture with bounded input
- [x] Artifact verification and manifest checks
- [x] Safe simulation replay
- [x] Deterministic policy evaluator
- [x] CLI with human and JSON output
- [x] Examples and demo fixtures
- [x] Unit/integration/edge-case tests
- [x] Packaging and entry point
- [x] Docker runtime recipe
- [x] README and docs
- [x] Governance files
- [x] CI/CD workflows
- [x] Benchmarks
- [x] Clean-install verification
- [x] GitHub publication and action verification

## Vouchline 0.2 release-candidate additions

- [x] Baseline artifact comparison with deterministic findings
- [x] JSON, SARIF 2.1.0, and JUnit XML renderers
- [x] OTLP/JSON adapter with bounded GenAI/MCP attribute mapping
- [ ] MCP/JSONL importer that performs no network access (future)
- [x] Contract fixtures for adapter normalization and schema compatibility
- [ ] Optional rebuildable SQLite index (future)
- [ ] Optional detached attestation interface and verification errors (future)
- [x] Security regression tests for adapter isolation and signature misuse
- [x] Updated README, API/CLI/reference docs, examples, and changelog
- [x] CI matrix and release workflow verification
- [x] Measured benchmark output with environment metadata
