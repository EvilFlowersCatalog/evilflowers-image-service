"""The figures' own metrics, on top of the kit's standard set (task duration, job outcome, catalog retries, capped
deliveries). Each is created on first use and is a no-op without OpenTelemetry.

Attributes stay low-cardinality: never a run id, a document id or a batch job name.
"""

from evilflowers_worker.observability.metrics import Instrument

REGIONS = Instrument(
    "counter", "{service}.figures.regions", "{region}", "Figure regions handled, by outcome (kept, a gate, error)"
)
CAPTION_DURATION = Instrument(
    "histogram", "{service}.caption.duration", "s", "Time to describe one figure through the Ollama endpoint"
)


def record_region(outcome: str) -> None:
    """``outcome``: kept, error, or the gate that dropped it (``too small`` → ``too_small``)."""
    REGIONS.add(1, {"outcome": outcome.replace(" ", "_")})


def record_caption(model: str, outcome: str, seconds: float) -> None:
    """``outcome``: described, unparsed (no description in the answer) or error."""
    CAPTION_DURATION.record(seconds, {"model": model, "outcome": outcome})
