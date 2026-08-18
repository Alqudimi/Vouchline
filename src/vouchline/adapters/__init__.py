"""Optional input adapters kept outside the Vouchline domain core."""

from .mcp_jsonl import messages_to_events
from .otlp_json import spans_to_events

__all__ = ["messages_to_events", "spans_to_events"]
