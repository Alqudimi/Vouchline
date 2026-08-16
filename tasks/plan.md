# Implementation Plan: Vouchline

## Overview

Build a production-grade, local-first Python CLI/library that captures AI tool-run events into redacted, hash-chained evidence artifacts; verifies integrity; safely replays recorded results without side effects; and evaluates deterministic regression policies.

## Architecture decisions

1. **Modular monolith:** Keep domain logic independent from the CLI and file system. This is large enough to demonstrate boundaries but small enough to maintain as an open-source repository.
2. **Pydantic v2 models:** Validate untrusted event and artifact input at the boundary and keep typed objects inside the domain.
3. **JSONL input plus JSON artifact:** JSONL is stream-friendly and portable; the artifact is self-contained and reviewable in pull requests.
4. **Hash chain, not fake signatures:** SHA-256 detects post-capture mutation but does not prove producer identity. The limitation is explicit in the docs.
5. **Simulation-only replay:** The replay engine consumes recorded outputs and imports no execution or network adapter. This is a security invariant tested in the suite.
6. **Stdlib-first domain:** Use Python standard library for canonical JSON, hashing, file I/O, and regex redaction. Keep runtime dependencies limited to Pydantic, Typer, and Rich.

## Task list

### Phase 1: Contract and domain foundation

- [ ] Task 1: Define typed events, artifacts, policies, reports, and error codes.
- [ ] Task 2: Implement canonical serialization and hash-chain integrity.
- [ ] Task 3: Implement recursive secret redaction with size and key limits.

### Checkpoint: Foundation

- [ ] Malformed events fail with stable codes.
- [ ] Same sanitized input produces the same hashes.
- [ ] Redaction tests prove secrets are absent from serialized output.

### Phase 2: Use cases

- [ ] Task 4: Capture JSONL into an artifact with bounded streaming input.
- [ ] Task 5: Verify artifact schema, chain, and manifest.
- [ ] Task 6: Replay verified artifacts in simulation mode.
- [ ] Task 7: Evaluate deterministic policies and produce findings.

### Checkpoint: Core behavior

- [ ] A sample run can be captured, verified, replayed, and asserted end to end.
- [ ] Tampering and missing tool responses produce non-zero, actionable failures.
- [ ] Replay cannot execute commands or network calls.

### Phase 3: CLI and developer experience

- [ ] Task 8: Add CLI commands, JSON output, stable exit codes, and readable errors.
- [ ] Task 9: Add examples, policy fixtures, and a demo script.
- [ ] Task 10: Add unit/integration/edge-case tests and coverage configuration.

### Checkpoint: Usability

- [ ] A new user can install locally and complete the quick start in under five commands.
- [ ] Help output documents all public commands.
- [ ] Example artifacts are reproducible from tracked input.

### Phase 4: Distribution and trust

- [ ] Task 11: Add pyproject packaging, Dockerfile, Makefile, and `.dockerignore`.
- [ ] Task 12: Add repository governance files and detailed documentation.
- [ ] Task 13: Add GitHub Actions for lint, format, type check, tests, coverage, audit, and build.
- [ ] Task 14: Add benchmarks for capture, verify, and replay.

### Checkpoint: Release candidate

- [ ] Clean-environment installation succeeds.
- [ ] All local quality gates pass.
- [ ] No tracked secrets or unsafe default execution paths exist.
- [ ] README claims match observed commands and outputs.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope drifts into a general observability platform | High | Keep web UI, server, LLM evaluation, and gateway features out of MVP. |
| Replay accidentally executes side effects | Critical | Simulation engine has no execution dependencies; add import and behavior tests. |
| Redaction misses credentials | High | Key-based plus pattern-based masking, conservative defaults, leak regression fixtures. |
| Schema becomes hard to evolve | Medium | Explicit `schema_version`, additive fields, migration notes, versioned examples. |
| CI reports false confidence | Medium | Test failures, malformed inputs, tampering, limits, and subprocess/network safety, not just happy paths. |
| Dependency maintenance grows | Medium | Small runtime dependency set and pinned development constraints. |

## Definition of done

The project is done when the documented quick start works from a clean virtual environment, the complete test suite and quality gates pass, a tampered artifact is rejected, a policy violation fails with a stable code, a replay is proven simulation-only, the wheel and Docker image build, and the repository contains the required open-source governance files.

## Vouchline 0.2 Upgrade Scope

The existing MVP plan is preserved. The release-candidate upgrade adds the following bounded slices:

1. **Baseline comparison:** compare two verified artifacts by event identity, tool outcomes, policy findings, and run status; emit deterministic findings and stable exit codes.
2. **CI reports:** render the same findings as JSON, SARIF 2.1.0, and JUnit XML without duplicating evaluation logic.
3. **Optional adapters:** translate bounded OTLP/JSON and MCP/JSONL exports into the existing event contract. Adapters remain outside the domain core and never open outbound connections.
4. **Optional local index:** maintain a rebuildable SQLite index as a derived read model; artifacts remain the source of truth.
5. **Detached attestations:** add a typed signing interface with an optional standard-library-compatible backend where appropriate; document that hash chains and signatures answer different questions.
6. **Release quality:** add contract fixtures, malformed-input tests, adapter safety tests, benchmark reporting, expanded examples, and release documentation.

### Upgrade acceptance criteria

- Existing v1 artifacts remain readable and verifiable.
- Every new report is derived from the same typed findings and has golden fixtures.
- Adapter imports are pure transformations over supplied bytes/objects and cannot invoke processes or networks.
- SQLite rebuild is idempotent and deleting the index does not delete or mutate artifacts.
- Signature failures are distinguishable from integrity failures and never downgrade verification.
- README quick starts, architecture diagrams, and CI examples execute against tracked fixtures.
