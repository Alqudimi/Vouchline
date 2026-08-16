# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | Yes, for security fixes |
| Older versions | No |

## Security model

Vouchline treats input JSONL and artifact files as untrusted. The MVP validates strict schemas, bounds event count and input bytes, redacts sensitive keys and common credential patterns before writing, canonicalizes data before hashing, and uses a replay engine that does not execute commands or make network requests.

The SHA-256 chain is an integrity check. It does not authenticate the producer, provide non-repudiation, or protect an artifact if the attacker can rewrite both the events and the manifest. Use signed detached attestations and a trusted key distribution process for those requirements; signing is not implemented in the MVP.

Vouchline is not a sandbox. Do not pass untrusted commands to it expecting replay or validation to contain those commands. Use an OS-level sandbox, container, or VM for untrusted execution.

## Reporting a vulnerability

Please do not report security vulnerabilities through public GitHub issues. Open a private vulnerability report through GitHub Security Advisories for `Alqudimi/Vouchline`, or contact the maintainer privately through the email listed in the GitHub profile.

Include the affected version, a minimal reproduction that contains no real secrets, impact, and a proposed mitigation if known. Please allow maintainers reasonable time to investigate and prepare a fix before public disclosure.

## Secret handling

Never include real API keys, access tokens, private keys, customer data, or production traces in an issue, pull request, fixture, benchmark, or test. Use the fake values in `examples/sample_run.jsonl` or clearly synthetic data.
