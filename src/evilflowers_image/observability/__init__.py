"""Traces, metrics, profiles and JSON logs of the image worker (the cluster's telemetry contract, IP-019).

Off unless the pod points it at a collector; every call here is safe either way.
"""

from evilflowers_image.observability import metrics
from evilflowers_image.observability.context import bind
from evilflowers_image.observability.logs import JsonFormatter
from evilflowers_image.observability.setup import endpoint, is_enabled, setup, shutdown
from evilflowers_image.observability.tracing import annotate, fail, span

__all__ = [
    "JsonFormatter",
    "annotate",
    "bind",
    "endpoint",
    "fail",
    "is_enabled",
    "metrics",
    "setup",
    "shutdown",
    "span",
]
