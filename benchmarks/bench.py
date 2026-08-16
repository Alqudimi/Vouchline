from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import partial

from vouchline.capture import build_artifact
from vouchline.integrity import verify_artifact
from vouchline.models import InputEvent, Producer
from vouchline.replay import replay_artifact


def make_events(count: int) -> list[InputEvent]:
    if count < 4 or count % 2 != 0:
        raise ValueError("benchmark count must be an even number >= 4")
    events = [
        InputEvent(
            event_id="event-1",
            sequence=1,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            kind="run.started",
            actor="benchmark",
            payload={},
        )
    ]
    sequence = 2
    for call_number in range(1, (count - 2) // 2 + 1):
        events.append(
            InputEvent(
                event_id=f"event-{sequence}",
                sequence=sequence,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind="tool.requested",
                actor="benchmark",
                call_id=f"call-{call_number}",
                payload={"tool": "search"},
            )
        )
        sequence += 1
        events.append(
            InputEvent(
                event_id=f"event-{sequence}",
                sequence=sequence,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                kind="tool.responded",
                actor="benchmark",
                call_id=f"call-{call_number}",
                payload={"status": "ok"},
            )
        )
        sequence += 1
    events.append(
        InputEvent(
            event_id=f"event-{sequence}",
            sequence=sequence,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            kind="run.finished",
            actor="benchmark",
            payload={"status": "completed"},
        )
    )
    return events


def measure(name: str, operation) -> dict[str, object]:
    started = time.perf_counter()
    value = operation()
    elapsed = time.perf_counter() - started
    return {"operation": name, "seconds": round(elapsed, 6), "result_type": type(value).__name__}


def main() -> None:
    results: list[dict[str, object]] = []
    for count in (1_000, 10_000):
        events = make_events(count)
        artifact = build_artifact(
            events,
            run_id=f"benchmark-{count}",
            producer=Producer(name="benchmark", version="0.1.0"),
            redaction_count=0,
        )
        verify_operation = partial(verify_artifact, artifact)
        replay_operation = partial(replay_artifact, artifact)
        results.append({"events": count, **measure("verify", verify_operation)})
        results.append({"events": count, **measure("replay", replay_operation)})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
