"""The Celery application: ``celery -A evilflowers_image.worker worker``.

The task name, queue and kwargs are a contract with the analyzer, which sends them, and with the catalog's routing;
they must not change:

=========================  =========================  =========================================
Task                       Queue                      Sent by
=========================  =========================  =========================================
evilflowers_image.figures  ``IMAGE_QUEUE``            analyzer (kwargs, ``RegionsJob``)
=========================  =========================  =========================================

Everything else is evilflowers-worker's ``create_app``: late acknowledgement, prefetch 1, the db-wide visibility
timeout, the scale-in protocol on SIGTERM, the delivery cap, telemetry and JSON logs. No result backend: the job
reports to the catalog.
"""

from evilflowers_worker.runtime import create_app

from evilflowers_image.settings import get_settings

settings = get_settings()
app = create_app("image", settings, include=["evilflowers_image.tasks"], queues=[settings.queue])
