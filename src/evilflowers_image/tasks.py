"""The figures tasks.

- ``evilflowers_image.figures``: the IP-018 catalog job, dispatched by evilflowers-analyzer-service with keyword
  arguments (``RegionsJob``). ``job`` (a batch: ``figures:0001-0008``) and ``attempt`` are optional; unknown kwargs
  are ignored.
- ``evilflowers_image.standalone.figures``: the books digitalizer's catalog-free job (``StandaloneFiguresJob``, #7),
  with the orchestrator's ``link`` / ``link_error`` callbacks.
"""

from typing import Any

from celery import Task, shared_task
from evilflowers_worker.contract import RegionsJob
from evilflowers_worker.runtime import JOB_TASK_OPTIONS, run_job, run_task

# The module that calls `create_app`: a pool child started by spawn imports only this one.
import evilflowers_image.worker  # noqa: F401
from evilflowers_image.jobs import FiguresJob
from evilflowers_image.standalone import TASK, StandaloneFigures, StandaloneFiguresJob

_standalone: StandaloneFigures | None = None


def standalone_handler() -> StandaloneFigures:
    """The process's handler, built on first use (its judges' circuit breakers live as long as the process)."""
    global _standalone
    if _standalone is None:
        _standalone = StandaloneFigures()
    return _standalone


@shared_task(name="evilflowers_image.figures", bind=True, **JOB_TASK_OPTIONS)
def figures(self: Task, **kwargs: Any) -> str:
    """Figure regions found by the analyzer's layout pass: crop, gate, decide, optional caption, report."""
    return run_job(self, FiguresJob, RegionsJob, kwargs)


@shared_task(name=TASK, bind=True, **JOB_TASK_OPTIONS)
def standalone_figures(self: Task, **kwargs: Any) -> dict[str, Any]:
    """Figure regions on cleaned leaves: crops, ``figures.json``, then the outcome file; ``{job, figures}``."""
    handler = standalone_handler()
    return run_task(
        self, handler.run, StandaloneFiguresJob, kwargs, on_capped=handler.give_up, on_invalid=handler.invalid
    )
