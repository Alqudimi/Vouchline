"""Optional input adapters kept outside the Vouchline domain core."""

from .otlp_json import spans_to_events

__all__ = ["spans_to_events"]
