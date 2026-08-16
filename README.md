# Vouchline

**Portable, replay-safe evidence for AI tool runs.**

[![CI](https://github.com/Alqudimi/Vouchline/actions/workflows/ci.yml/badge.svg)](https://github.com/Alqudimi/Vouchline/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-2ea44f)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange)](CHANGELOG.md)

Vouchline is a local-first Python library and CLI that turns an AI agent or tool execution into a **redacted, hash-chained evidence artifact**. The artifact can be verified after transport, replayed in simulation without executing side effects, and used as a deterministic CI policy input.

> **Vouchline is an evidence boundary, not an agent framework, MCP gateway, sandbox, or LLM judge.** It records what happened, proves whether the record was modified, and lets you inspect the recorded path safely.

## Why Vouchline exists

A final answer rarely explains why an agent failed. The useful evidence is spread across tool requests, tool responses, policy decisions, timing, and run metadata. Production traces are often provider-specific, while raw logs are hard to share safely and expensive to reproduce.

Vouchline provides a small, portable contract for the lifecycle:

```text
JSONL events → redact → validate → hash-chain → verify → safe replay → CI assertions
```

It complements protocol inspectors, observability platforms, security gateways, and model-evaluation tools rather than replacing them.

## Features

| Capability | What it provides |
|---|---|
| **Redacted capture** | Recursively masks sensitive keys and common token patterns before persistence. |
| **Tamper evidence** | SHA-256 event chain plus artifact manifest detects post-capture mutation. |
| **Safe replay** | Reconstructs recorded tool outcomes without launching processes or making network calls. |
| **Deterministic policies** | Deny tools, require tools, cap tool calls, and deny response statuses. |
| **Portable contract** | Versioned JSON artifact with a documented schema and no database requirement. |
| **Automation-ready CLI** | Human output for developers and stable JSON/exit codes for CI. |
| **Small core** | Framework-neutral domain layer with adapters kept outside the replay boundary. |

## Quick start

Vouchline requires Python 3.11 or newer.

```bash
git clone https://github.com/Alqudimi/Vouchline.git
cd Vouchline
python -m pip install -e '.[dev]'

vouchline capture examples/sample_run.jsonl --output .demo/run.json --run-id demo-001
vouchline verify .demo/run.json
vouchline replay .demo/run.json
vouchline assert .demo/run.json --policy examples/policy.json
```

The sample input contains a deliberately fake bearer value. Vouchline reports one redacted field and persists only `[REDACTED]`; no real credential is used.

For machine-readable automation:

```bash
vouchline capture examples/sample_run.jsonl --output .demo/run.json --json
vouchline verify .demo/run.json --json
vouchline replay .demo/run.json --json
vouchline assert .demo/run.json --policy examples/policy.json --json
```

Input can also be streamed from standard input:

```bash
cat examples/sample_run.jsonl | vouchline capture - --output .demo/stdin-run.json
```

## What the artifact contains

An artifact contains a versioned producer identity, run identity, redaction summary, ordered events, and an integrity manifest. Core events are `run.started`, `tool.requested`, `tool.responded`, `policy.decision`, and `run.finished`. Tool requests and responses are paired by `call_id`.

The hash chain is intentionally honest: it detects mutation but does not authenticate the producer. Detached signatures and hardware-backed attestations are roadmap items, not hidden behavior.

See the full [Artifact Schema v1](docs/artifact-schema.md) and [architecture decision record](docs/architecture.md).

## Security boundary

Replay is **simulation-only in the MVP**. It verifies the artifact, consumes recorded responses, and produces a replay report. It does not import or call `subprocess`, sockets, HTTP clients, MCP SDKs, or model providers. Live execution is intentionally a separate future adapter and is not reachable through the default CLI.

The parser treats JSONL and artifact files as untrusted input. It uses strict Pydantic models, bounded event/byte limits, safe JSON parsing, conservative redaction, and typed failures. Vouchline is not a sandbox; use an OS or container sandbox for untrusted code.

Read [SECURITY.md](SECURITY.md) before reporting a vulnerability.

## CLI reference

| Command | Purpose |
|---|---|
| `vouchline capture INPUT --output ARTIFACT` | Convert JSONL events into a redacted artifact. Use `-` for stdin. |
| `vouchline verify ARTIFACT` | Validate schema, event ordering, hash chain, and manifest. |
| `vouchline replay ARTIFACT` | Simulate the recorded tool path without side effects. |
| `vouchline assert ARTIFACT --policy POLICY.json` | Run deterministic policy assertions. |
| `vouchline version` | Print the installed version. |

Exit codes are stable: `0` means pass, `2` means invalid input, `3` means integrity failure, `4` means replay or policy failure, and `5` means an unexpected internal error.

## Development

```bash
make install
make test
make lint
make format
make typecheck
make audit
make build
make bench
make demo
```

The test suite covers valid lifecycle paths, malformed records, size limits, nested redaction, token-pattern redaction, tampering, missing and unmatched responses, policy violations, CLI JSON output, exit codes, and the simulation-only replay invariant.

The benchmark measures verification and simulation replay for 1,000 and 10,000 events:

```bash
python benchmarks/bench.py
```

Benchmark results depend on the machine and Python build; Vouchline does not publish an unmeasured throughput claim.

## Architecture

```text
JSONL / adapter input
        |
        v
  CaptureService → Redactor → EventValidator
        |                         |
        v                         v
  ArtifactWriter ← IntegrityHasher
        |
        +→ ArtifactReader → Verifier → SafeReplayEngine
                                      ↘ PolicyEvaluator
                                      ↘ ReportRenderer
```

The core models, canonicalization, redaction, integrity, replay, and policy modules do not depend on a web framework or a model provider. File I/O and the CLI are adapters around those use cases. This keeps the evidence contract reusable by future MCP, OTLP, hook, SQLite, or object-storage adapters.

## Roadmap

### Next

The next release family can add MCP and OTLP import adapters, golden baseline comparison, SARIF/JUnit reports, SQLite indexing, and detached signatures. Each feature must consume the stable artifact contract and preserve simulation-only replay as the default.

### Later

A local viewer, provider-neutral plugin registry, retention policies, team review workflows, and remote evidence registries are possible extensions. Multi-user hosting and a web dashboard are intentionally not part of the MVP.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), read the [architecture](docs/architecture.md), run the full quality gate, and include a regression test for behavior changes. New adapters should translate into the versioned event contract instead of placing provider-specific logic in the replay engine.

## License

Vouchline is released under the [MIT License](LICENSE).
