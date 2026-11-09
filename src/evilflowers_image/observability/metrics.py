"""The worker's metrics, declared once; each is created on first use and is a no-op without OpenTelemetry.

Attributes stay low-cardinality: never a run id or document id (those go on spans and log lines).
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

from evilflowers_image.observability.otel import SCOPE, metrics

# Seconds. Covers a 50 ms crop up to a 30 min book with captions.
DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800)

_lock = threading.Lock()


@dataclass(eq=False)
class Instrument:
    kind: Literal["counter", "histogram"]
    name: str
    unit: str
    description: str
    buckets: tuple[float, ...] | None = None
    _created: Any = field(default=None, init=False, repr=False)

    def _get(self):
        if metrics is None:
            return None
        if self._created is None:
            with _lock:
                if self._created is None:
                    # A proxy meter: its instruments become real once `setup()` sets the provider.
                    meter = metrics.get_meter(SCOPE)
                    if self.kind == "counter":
                        self._created = meter.create_counter(self.name, self.unit, self.description)
                    else:
                        self._created = meter.create_histogram(
                            self.name,
                            self.unit,
                            self.description,
                            explicit_bucket_boundaries_advisory=list(self.buckets or DURATION_BUCKETS),
                        )
        return self._created

    def add(self, value: float = 1, attributes: dict[str, Any] | None = None) -> None:
        if (instrument := self._get()) is not None:
            instrument.add(value, attributes or {})

    def record(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        if (instrument := self._get()) is not None:
            instrument.record(value, attributes or {})


TASK_DURATION = Instrument("histogram", "image.task.duration", "s", "Celery task run time")
JOB_OUTCOME = Instrument("counter", "image.job.outcome", "{job}", "IP-018 jobs reported to the catalog, by outcome")
REGIONS = Instrument(
    "counter", "image.figures.regions", "{region}", "Figure regions handled, by outcome (kept, a gate, error)"
)
CAPTION_DURATION = Instrument(
    "histogram", "image.caption.duration", "s", "Time to describe one figure through the Ollama endpoint"
)
CATALOG_RETRIES = Instrument(
    "counter", "image.catalog.retries", "{retry}", "Retried calls to the catalog ingestion API"
)


def record_job(job: str, outcome: str) -> None:
    """``outcome``: done, failed or not_running (the catalog refused the results)."""
    JOB_OUTCOME.add(1, {"job": job, "outcome": outcome})


def record_region(outcome: str) -> None:
    """``outcome``: kept, error, or the gate that dropped it (``too small`` → ``too_small``)."""
    REGIONS.add(1, {"outcome": outcome.replace(" ", "_")})


def record_caption(model: str, outcome: str, seconds: float) -> None:
    """``outcome``: described, unparsed (no description in the answer) or error."""
    CAPTION_DURATION.record(seconds, {"model": model, "outcome": outcome})
