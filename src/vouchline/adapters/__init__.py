"""Optional input adapters kept outside the Vouchline domain core."""

from .mcp_jsonl import mcp_lines_to_events
from .otlp_json import spans_to_events

__all__ = ["mcp_lines_to_events", "spans_to_events"]
