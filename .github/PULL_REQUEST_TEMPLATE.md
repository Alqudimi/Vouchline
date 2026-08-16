## Summary

Describe the user problem and the smallest change that solves it.

## Design

Explain the affected module boundary and any schema or CLI compatibility impact.

## Verification

- [ ] `pytest -q`
- [ ] `ruff check src tests benchmarks`
- [ ] `ruff format --check src tests benchmarks`
- [ ] `mypy src`
- [ ] Documentation updated for observable behavior
- [ ] No real secrets or private traces are included

## Security and replay boundary

Describe whether this change touches redaction, integrity, policy, or replay. Confirm that the default replay path remains simulation-only.

## Checklist

- [ ] The change is focused and has regression coverage.
- [ ] Public errors and exit codes remain stable or the change is documented.
- [ ] README, changelog, or schema docs are updated where appropriate.
