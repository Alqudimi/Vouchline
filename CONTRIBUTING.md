# Contributing to Vouchline

Thank you for contributing. Vouchline is intentionally small and contract-first: a contribution should make evidence safer, more portable, more verifiable, or easier to adopt without turning the project into a general observability platform.

## Before opening an issue

Search existing issues and read [the architecture document](docs/architecture.md) and [Artifact Schema v1](docs/artifact-schema.md). A feature proposal should explain the user problem, the boundary it belongs to, the compatibility impact, and how it will be tested without real credentials or external services.

## Development setup

```bash
git clone https://github.com/Alqudimi/Vouchline.git
cd Vouchline
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests benchmarks
ruff format --check src tests benchmarks
mypy src
```

## Contribution rules

Keep domain logic framework-neutral. Validate untrusted input at the boundary, use typed errors with stable codes, and prefer additive schema changes. Do not add provider-specific behavior to `replay.py`; replay must remain simulation-only unless a separately reviewed execution adapter and security model are introduced.

New behavior requires tests for the success path and at least one invalid or failure path. Security-sensitive changes must include a regression test demonstrating the relevant invariant. Documentation changes should include the exact command a maintainer can run to verify the claim.

## Pull requests

Use a focused branch and a Conventional Commit-style title such as `feat: add otlp event adapter`, `fix: reject broken hash chains`, or `docs: clarify artifact schema`. Explain the problem, the design, tests run, and any compatibility or security impact. Keep unrelated refactors out of the same pull request.

Every pull request must pass the repository CI checks. Reviewers will look for schema stability, secret handling, deterministic output, actionable error messages, and whether the README remains truthful.

## Adding an adapter

An adapter should parse an external format into `InputEvent` values and remain outside the core replay boundary. It must validate third-party data, avoid storing raw credentials, document its source format/version, and include fixtures that do not require network access. If the adapter introduces a new event kind, use an `extension.*` name first and propose a schema change before promoting it to a core kind.

## Reporting vulnerabilities

Do not open a public issue for a security vulnerability. Follow [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
