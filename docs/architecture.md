# Vouchline Architecture

## Product vision

Vouchline is a local-first evidence ledger for AI agent and tool executions. It turns a run into a portable, redacted, tamper-evident artifact that can be verified, replayed without side effects, and used as a deterministic CI regression input.

The project deliberately sits below dashboards and above raw process logs. It does not own the agent runtime, the model provider, or the tool server. It owns the evidence boundary.

## Problem statement

Agent and tool failures are difficult to reproduce because the useful context is distributed across model calls, tool requests, tool responses, policy decisions, timing, and environment metadata. Existing tools are strong at inspecting a live MCP connection, observing production traces, evaluating model quality, or enforcing runtime policies, but teams still need a small neutral artifact that can be shared and replayed safely.

## Product principles

| Principle | Design consequence |
|---|---|
| Evidence before interpretation | Preserve ordered events and integrity metadata before adding evaluators. |
| Safe by default | Replay consumes recorded results and never launches a process or network request. |
| Portable | JSONL input and versioned JSON artifact; no database required for the core path. |
| Redact at the boundary | Secrets are removed before persistence, not after an artifact is shared. |
| Deterministic where possible | Canonical JSON, stable event ordering, explicit exit codes, and structural assertions. |
| Framework-neutral | The core does not import MCP, LangChain, OpenAI, or a model SDK. |
| Honest cryptography | Hash-chain integrity is not a signature, identity proof, or non-repudiation. |

## MVP scope

The MVP implements a Python library and CLI with the following complete paths:

1. Capture a versioned JSONL event stream into a redacted artifact.
2. Validate event schemas and reject malformed or unknown required fields.
3. Compute and verify a SHA-256 hash chain and artifact manifest.
4. Replay a recorded run in simulation mode using only recorded tool results.
5. Evaluate declarative policy assertions such as forbidden tool names, maximum tool calls, and required tools.
6. Export concise JSON and human-readable terminal reports with stable exit codes.
7. Provide sample data, a full test suite, lint/type checks, packaging, Docker, and GitHub Actions.

The MVP does not execute arbitrary commands, call external networks, invoke an LLM, or store a server-side database.

## Domain model

### Evidence artifact

An artifact is a JSON document with this shape:

```json
{
  "schema_version": "v1",
  "artifact_id": "uuid",
  "run_id": "string",
  "producer": {"name": "string", "version": "string"},
  "created_at": "RFC3339 timestamp",
  "redaction": {"profile": "default", "redacted_fields": 0},
  "events": ["ordered Event objects"],
  "manifest": {
    "event_count": 0,
    "first_hash": "sha256 hex",
    "last_hash": "sha256 hex",
    "artifact_sha256": "sha256 hex"
  }
}
```

### Events

The MVP uses typed event kinds: `run.started`, `tool.requested`, `tool.responded`, `policy.decision`, and `run.finished`. Each event has a sequence number, stable event ID, timestamp, actor, payload, previous hash, and current hash. Tool request and response events carry a `call_id`; replay pairs them without relying on wall-clock time.

Unknown event kinds can be preserved as `extension.*` events only when the producer marks them as extensions. Unknown core kinds fail validation so a typo cannot silently weaken a policy or a replay.

## Component boundaries

```text
JSONL / adapter input
        |
        v
  CaptureService ----> Redactor ----> EventValidator
        |                                 |
        v                                 v
  ArtifactWriter <---- IntegrityHasher <---+
        |
        +----> ArtifactReader ---> Verifier
                                      |
                                      +--> SafeReplayEngine
                                      +--> PolicyEvaluator
                                      +--> ReportRenderer
```

The domain models, canonicalization, redaction rules, integrity algorithm, replay engine, and policy evaluator are framework-independent. The CLI is an adapter around these use cases. File I/O is isolated behind small reader/writer ports so future SQLite, object storage, or HTTP adapters do not change domain behavior.

## Replay safety model

The replay engine accepts a verified artifact and a `ReplayMode.SIMULATED` value. It maps each `tool.requested` to the matching `tool.responded` and produces a replay report with the same call order, recorded status, and missing-result diagnostics. It never imports `subprocess`, `socket`, `httpx`, or a tool SDK. A future live executor must be a separately named adapter with explicit opt-in and a distinct policy boundary; it is outside MVP.

## Redaction model

Redaction recursively walks JSON objects and arrays. It masks values for configured sensitive key names such as `api_key`, `authorization`, `token`, `password`, and `secret`, and replaces values matching common credential patterns. The persisted artifact contains only the redacted value and a count. The original value is never written to the artifact, logs, or exception messages.

Redaction is intentionally conservative: it may remove more than a provider-specific secret scanner, but it must not leak secrets. A `--no-redact` flag is not part of the MVP. The library accepts an explicit profile object for future provider-specific rules.

## Policy model

Policies are declarative JSON/YAML-like documents represented internally as typed rules:

| Rule | Example | Failure |
|---|---|---|
| `deny_tools` | `delete_file`, `send_email` | Any matching request is denied. |
| `max_tool_calls` | `10` | Total requests exceed the budget. |
| `require_tools` | `search`, `fetch` | A required tool never appears. |
| `deny_statuses` | `error`, `timeout` | A response has a forbidden status. |

The evaluator is deterministic and returns individual findings plus a summary. It does not infer intent and does not call an LLM.

## Error semantics

All public failures use a typed exception hierarchy and stable machine-readable codes. The CLI maps them to exit codes:

| Exit code | Meaning |
|---:|---|
| 0 | Operation passed. |
| 2 | Input, schema, or policy configuration error. |
| 3 | Integrity verification failed or evidence is unsafe to consume. |
| 4 | Replay or policy assertion failed. |
| 5 | Unexpected internal failure. |

CLI output uses a human message plus a JSON form with `code`, `message`, and `details`. Unexpected failures are normalized to a stable internal-error response; the MVP does not expose a `--debug` flag or raw tracebacks through the CLI.

## Security model

The threat model treats artifacts and event streams as untrusted input. The parser limits event count and serialized size, treats path-like or command-like content as inert data rather than executing it, avoids unsafe deserialization, canonicalizes data before hashing, and never evaluates arbitrary expressions from policy files. JSON is the only persisted interchange format in MVP.

The artifact hash chain detects modification after capture. It does not authenticate the producer. A future signing extension may add detached signatures without changing the event contract.

## Performance strategy

Capture and verification are linear in event count, with one canonical serialization and one SHA-256 digest per event. Redaction is linear in the number of JSON nodes. The CLI streams JSONL input and enforces configurable event and byte limits before materializing the artifact. MVP benchmarks cover capture, verify, and replay for 1,000 and 10,000 events.

## Release-candidate extensions

Vouchline 0.2 adds a comparison and reporting layer above verified artifacts. `compare_artifacts` verifies both inputs first, then compares event counts, tool identities, tool outcomes, and terminal run status. It produces typed `ComparisonFinding` values; JSON, SARIF, and JUnit are renderers over that same report and do not implement separate policy logic.

The `adapters.otlp_json` module is a pure transformation boundary. It accepts an already-loaded OTLP/JSON object, extracts bounded span data, and maps tool spans to request/response events or preserves other spans as `extension.otlp.span`. It does not import an OTLP SDK, open a receiver, make network calls, or execute tools. Persistence and hashing remain the responsibility of the normal capture path, so redaction still occurs before artifact writing.

## Extension strategy

The public artifact contract is versioned. Additive fields are preferred; removing or changing required fields requires a new schema version. MCP JSON-RPC and OTLP/JSON normalization now map captured external data into the same event vocabulary without network access. Future adapters can map Claude/Codex hooks or Langfuse exports, while future sinks can write SQLite or object storage. Future outputs may include an HTML report without coupling the core to a web server.

## Non-functional requirements

| Area | MVP target |
|---|---|
| Python | 3.11+ |
| Determinism | Same sanitized input produces byte-stable event hashes and stable reports. |
| Safety | Replay test suite proves no subprocess/network imports or calls occur. |
| Quality | Unit, integration, property-style edge cases, coverage report, ruff, mypy. |
| Packaging | `pip install vouchline`-compatible wheel metadata and `vouchline` entry point. |
| Operations | Structured JSON output, explicit exit codes, no secrets in logs. |
| Distribution | MIT license, Docker image recipe, GitHub Actions, release-ready metadata. |

## Roadmap

### Advanced features

The next release family can add SQLite indexing, signed attestations, and a small local web viewer. Those features must consume the stable artifact contract rather than alter the core replay safety guarantees.

### Future

Longer-term work may add provider-neutral plugins, remote evidence registries, team review workflows, retention policies, and hardware-backed signing. None of these are required for the MVP and none should be simulated by placeholder code.
