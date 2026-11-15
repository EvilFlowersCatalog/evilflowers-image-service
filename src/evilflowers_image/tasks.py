"""The IP-018 figures job, dispatched by evilflowers-analyzer-service with keyword arguments (``RegionsJob``).

``job`` (a batch: ``figures:0001-0008``) and ``attempt`` are optional; unknown kwargs are ignored.
"""

from typing import Any

from celery import Task, shared_task
from evilflowers_worker.contract import RegionsJob
from evilflowers_worker.runtime import JOB_TASK_OPTIONS, run_job

# The module that calls `create_app`: a pool child started by spawn imports only this one.
import evilflowers_image.worker  # noqa: F401
from evilflowers_image.jobs import FiguresJob


@shared_task(name="evilflowers_image.figures", bind=True, **JOB_TASK_OPTIONS)
def figures(self: Task, **kwargs: Any) -> str:
    """Figure regions found by the analyzer's layout pass: crop, gate, optional caption, report."""
    return run_job(self, FiguresJob, RegionsJob, kwargs)
