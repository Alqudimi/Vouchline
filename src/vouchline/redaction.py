"""Conservative, pre-persistence redaction for untrusted event payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .errors import LimitError

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(
        r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    count: int


def _key_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _redact_string(value: str) -> RedactionResult:
    redacted = value
    count = 0
    for pattern in _SECRET_PATTERNS:
        redacted, substitutions = pattern.subn(_REDACTED, redacted)
        count += substitutions
    return RedactionResult(redacted, count)


def redact(value: Any, *, max_depth: int = 50, _depth: int = 0) -> RedactionResult:
    """Return a redacted copy without mutating the input."""
    if _depth > max_depth:
        raise LimitError("payload nesting exceeds the configured safety limit")
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        items: list[Any] = []
        total = 0
        for item in value:
            result = redact(item, max_depth=max_depth, _depth=_depth + 1)
            items.append(result.value)
            total += result.count
        return RedactionResult(items, total)
    if isinstance(value, dict):
        result_map: dict[str, Any] = {}
        total = 0
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _key_name(key) in _SENSITIVE_KEYS:
                result_map[key] = _REDACTED
                total += 1
                continue
            result = redact(raw_value, max_depth=max_depth, _depth=_depth + 1)
            result_map[key] = result.value
            total += result.count
        return RedactionResult(result_map, total)
    return RedactionResult(value, 0)
