"""The Celery application: ``celery -A evilflowers_image.worker worker``.

The task name, queue and kwargs are a contract with the analyzer, which sends
them, and with the catalog's routing; they must not change:

=========================  =========================  =========================================
Task                       Queue                      Sent by
=========================  =========================  =========================================
evilflowers_image.figures  ``IMAGE_QUEUE``            analyzer (kwargs)
=========================  =========================  =========================================

Nobody waits for a task's result (the job reports to the catalog), so there is
no result backend.
"""

from celery import Celery

from evilflowers_image.observability.signals import connect
from evilflowers_image.settings import Settings, get_settings

TASK_PREFIX = "evilflowers_image"


class CeleryConfig:
    """Shared with the sibling extraction services (analyzer, text, equation) where it can be."""

    def __init__(self, settings: Settings):
        self.broker_url = settings.redis_url
        self.broker_connection_retry_on_startup = True
        # The job acknowledges late; Redis must not redeliver a book still being cropped.
        self.broker_transport_options = {"visibility_timeout": settings.broker_visibility_timeout}

        self.task_serializer = "json"
        self.result_serializer = "json"
        self.accept_content = ["json"]
        self.timezone = "Europe/Bratislava"
        self.enable_utc = True

        self.task_default_queue = settings.queue
        self.task_routes = {f"{TASK_PREFIX}.*": {"queue": settings.queue}}
        self.worker_prefetch_multiplier = 1
        # A worker that dies mid-book has the message redelivered; the catalog answers 409 to a
        # run that finished meanwhile, so a second delivery is harmless.
        self.task_acks_late = True
        self.task_reject_on_worker_lost = True
        # Monitoring (Flower, `celery events`).
        self.worker_send_task_events = True
        self.task_send_sent_event = True


def create_app(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()
    app = Celery("evilflowers_image", include=["evilflowers_image.tasks"])
    app.config_from_object(CeleryConfig(settings))
    return app


# Traces, metrics, profiles and JSON logs; off unless the pod points them at a collector.
connect()
app = create_app()
