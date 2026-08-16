"""Canonical JSON and digest helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def canonical_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and artifact output."""
    return json.dumps(
        value,
        default=jsonable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def event_digest(event: dict[str, Any], previous_hash: str) -> str:
    return sha256_hex({"previous_hash": previous_hash, "event": event})


def artifact_digest(artifact: dict[str, Any]) -> str:
    """Hash an artifact while excluding the digest field that stores this hash."""
    normalized = json.loads(canonical_bytes(artifact))
    normalized.setdefault("manifest", {})["artifact_sha256"] = ""
    return sha256_hex(normalized)
