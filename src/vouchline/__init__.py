"""Vouchline: portable, replay-safe evidence artifacts for AI tool runs."""

from .adapters import spans_to_events
from .capture import build_artifact, load_artifact, parse_jsonl, write_artifact
from .comparison import compare_artifacts
from .integrity import verify_artifact
from .models import Artifact, ComparisonReport, InputEvent, Policy, Producer
from .policy import evaluate_policy
from .replay import replay_artifact

__all__ = [
    "Artifact",
    "ComparisonReport",
    "InputEvent",
    "Policy",
    "Producer",
    "build_artifact",
    "compare_artifacts",
    "evaluate_policy",
    "load_artifact",
    "parse_jsonl",
    "replay_artifact",
    "verify_artifact",
    "write_artifact",
    "spans_to_events",
]

__version__ = "0.2.0"
