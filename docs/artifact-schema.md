# Vouchline Artifact Schema v1

## Purpose

The Vouchline artifact is a portable JSON document for a single tool-run execution. It is designed to be safe to share after redaction, verifiable after transport, and replayable in simulation mode.

## Event envelope

Every event has these required fields:

| Field | Type | Requirement |
|---|---|---|
| `schema_version` | string | Must be `v1`. |
| `event_id` | string | Producer-scoped identifier. |
| `sequence` | integer | Starts at `1` and is contiguous. |
| `timestamp` | RFC3339 string | Event observation time. |
| `kind` | string | One of the core kinds or `extension.*`. |
| `actor` | string | Component that emitted the event. |
| `call_id` | string or null | Required for paired tool request/response events. |
| `payload` | object | Redacted event data. |

The core event kinds are `run.started`, `tool.requested`, `tool.responded`, `policy.decision`, and `run.finished`. A `tool.requested` payload must contain a non-empty string `tool`. A `tool.responded` payload must contain a non-empty string `status`. The replay engine pairs requests and responses by `call_id`, not by timestamp.

## Integrity fields

Captured events add `previous_hash` and `event_hash`. The first event uses 64 zeroes as `previous_hash`. The event hash is SHA-256 over canonical JSON containing the event without the two integrity fields plus its `previous_hash`.

The artifact manifest stores the event count, first and last event hashes, and an `artifact_sha256`. The artifact hash is computed over canonical JSON after setting `manifest.artifact_sha256` to an empty string. Canonical JSON uses UTF-8, sorted object keys, compact separators, and no ASCII escaping.

> A hash chain detects modification after capture. It does not prove who created the artifact and is not a cryptographic signature or non-repudiation proof.

## Example

```json
{
  "schema_version": "v1",
  "artifact_id": "a-run-id",
  "run_id": "support-001",
  "producer": {"name": "example-adapter", "version": "1.0.0"},
  "created_at": "2026-08-16T00:00:00Z",
  "redaction": {"profile": "default", "redacted_fields": 1},
  "events": [
    {
      "schema_version": "v1",
      "event_id": "event-1",
      "sequence": 1,
      "timestamp": "2026-08-16T00:00:00Z",
      "kind": "tool.requested",
      "actor": "agent",
      "call_id": "call-1",
      "payload": {"tool": "search", "arguments": {"token": "[REDACTED]"}},
      "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "event_hash": "<64 lowercase hex characters>"
    }
  ],
  "manifest": {
    "event_count": 1,
    "first_hash": "<64 lowercase hex characters>",
    "last_hash": "<64 lowercase hex characters>",
    "artifact_sha256": "<64 lowercase hex characters>"
  }
}
```

## Compatibility rules

Producers should add optional payload fields rather than change the meaning of existing fields. New core event kinds require a schema version change or a documented extension proposal. Consumers must reject unknown required top-level fields and may preserve `extension.*` events for future adapters.

## Safe replay contract

A conforming Vouchline MVP replay implementation must verify the artifact before consuming it, must not make network requests, must not launch a process, and must report missing or unmatched tool responses. Live execution is intentionally outside this contract.
