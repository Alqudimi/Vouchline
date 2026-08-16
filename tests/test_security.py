from __future__ import annotations

import inspect
import io
import json

import pytest

from vouchline.capture import parse_jsonl
from vouchline.errors import InputError, LimitError
from vouchline.redaction import redact
from vouchline.replay import replay_artifact


def test_common_secret_patterns_are_redacted() -> None:
    result = redact(
        {
            "message": "Bearer abcdefghijklmnop",
            "nested": "ghp_" + "abcdefghijklmnopqrstuvwxyz123456",
            "api_key": "explicit-secret",
        }
    )
    assert result.count >= 3
    serialized = json.dumps(result.value)
    assert "abcdefghijklmnop" not in serialized
    assert "explicit-secret" not in serialized


def test_redaction_rejects_excessive_nesting() -> None:
    value: object = "leaf"
    for _ in range(55):
        value = [value]
    with pytest.raises(LimitError):
        redact(value, max_depth=10)


def test_unknown_core_event_is_rejected() -> None:
    raw = {
        "schema_version": "v1",
        "event_id": "1",
        "sequence": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "kind": "tool.maybe-dangerous",
        "actor": "agent",
        "payload": {},
    }
    with pytest.raises(InputError):
        parse_jsonl(io.StringIO(json.dumps(raw) + "\n"))


def test_replay_module_has_no_execution_or_network_adapter() -> None:
    source = inspect.getsource(replay_artifact)
    assert "subprocess" not in source
    assert "socket" not in source
    assert "httpx" not in source
