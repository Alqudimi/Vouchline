from datetime import UTC, datetime

import pytest

from vouchline.models import Artifact, EvidenceEvent, Manifest, Policy, Producer, RedactionSummary
from vouchline.policy import evaluate_policy


@pytest.fixture
def producer():
    return Producer(name="test", version="0.1.0")


@pytest.fixture
def redaction():
    return RedactionSummary(profile="test", redacted_fields=0)


def create_artifact(events, producer, redaction):
    # This is a simplified artifact creation for testing policy logic
    # In a real scenario, hashes must be valid, but evaluate_policy calls verify_artifact
    # which we might need to mock or provide valid hashes for.

    # Let's provide a dummy manifest and valid-looking hashes to satisfy verify_artifact
    manifest = Manifest(
        event_count=len(events), first_hash="a" * 64, last_hash="b" * 64, artifact_sha256="c" * 64
    )

    return Artifact(
        artifact_id="test-artifact",
        run_id="test-run",
        producer=producer,
        created_at=datetime.now(UTC),
        redaction=redaction,
        events=events,
        manifest=manifest,
    )


def test_policy_cost_limit_exceeded(producer, redaction, monkeypatch):
    # Mock verify_artifact to avoid hash validation overhead in logic test
    monkeypatch.setattr("vouchline.policy.verify_artifact", lambda x: None)

    events = [
        EvidenceEvent(
            event_id="1",
            sequence=1,
            timestamp=datetime.now(UTC),
            kind="tool.requested",
            actor="agent",
            payload={"tool": "search"},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
        EvidenceEvent(
            event_id="2",
            sequence=2,
            timestamp=datetime.now(UTC),
            kind="tool.responded",
            actor="system",
            payload={"status": "success", "usage": {"cost": 0.05, "total_tokens": 100}},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
        EvidenceEvent(
            event_id="3",
            sequence=3,
            timestamp=datetime.now(UTC),
            kind="tool.requested",
            actor="agent",
            payload={"tool": "search"},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
        EvidenceEvent(
            event_id="4",
            sequence=4,
            timestamp=datetime.now(UTC),
            kind="tool.responded",
            actor="system",
            payload={"status": "success", "usage": {"cost": 0.06, "total_tokens": 150}},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
    ]

    artifact = create_artifact(events, producer, redaction)

    # Total cost = 0.11, Total tokens = 250

    # Test cost limit
    policy = Policy(max_cost=0.10)
    report = evaluate_policy(artifact, policy)
    assert report.passed is False
    assert any(f.rule == "max_cost" for f in report.findings)
    assert report.total_cost == 0.11

    # Test token limit
    policy = Policy(max_total_tokens=200)
    report = evaluate_policy(artifact, policy)
    assert report.passed is False
    assert any(f.rule == "max_total_tokens" for f in report.findings)
    assert report.total_tokens == 250


def test_policy_within_budget(producer, redaction, monkeypatch):
    monkeypatch.setattr("vouchline.policy.verify_artifact", lambda x: None)

    events = [
        EvidenceEvent(
            event_id="1",
            sequence=1,
            timestamp=datetime.now(UTC),
            kind="tool.requested",
            actor="agent",
            payload={"tool": "search"},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
        EvidenceEvent(
            event_id="2",
            sequence=2,
            timestamp=datetime.now(UTC),
            kind="tool.responded",
            actor="system",
            payload={"status": "success", "usage": {"cost": 0.01, "total_tokens": 10}},
            previous_hash="0" * 64,
            event_hash="0" * 64,
        ),
    ]

    artifact = create_artifact(events, producer, redaction)

    policy = Policy(max_cost=0.05, max_total_tokens=100)
    report = evaluate_policy(artifact, policy)
    assert report.passed is True
    assert report.total_cost == 0.01
    assert report.total_tokens == 10
    assert len(report.findings) == 0


def test_policy_missing_usage_data(producer, redaction, monkeypatch):
    monkeypatch.setattr("vouchline.policy.verify_artifact", lambda x: None)

    events = [
        EvidenceEvent(
            event_id="1",
            sequence=1,
            timestamp=datetime.now(UTC),
            kind="tool.responded",
            actor="system",
            payload={"status": "success"},  # No usage info
            previous_hash="0" * 64,
            event_hash="0" * 64,
        )
    ]

    artifact = create_artifact(events, producer, redaction)

    policy = Policy(max_cost=0.05)
    report = evaluate_policy(artifact, policy)
    assert report.passed is True
    assert report.total_cost == 0.0
    assert report.total_tokens == 0
