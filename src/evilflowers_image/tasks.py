"""The IP-018 figures job, dispatched by evilflowers-analyzer-service with keyword arguments.

``**_`` keeps the worker compatible with arguments a newer analyzer adds.
"""

from celery import shared_task

from evilflowers_image.jobs import FiguresJob, Outcome


@shared_task(name="evilflowers_image.figures", acks_late=True)
def figures(run_id: str, source: str, output_dir: str, regions: list[dict], **_) -> Outcome:
    """Figure regions found by the analyzer's layout pass: crop, gate, optional caption, report."""
    return FiguresJob(run_id, source, output_dir, regions).run()
