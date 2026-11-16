"""The Celery application: ``celery -A evilflowers_image.worker worker``.

The task names, queues and kwargs are a contract with their senders and with the catalog's routing; they must not
change:

=====================================  ==========================================  ===================================
Task                                   Queue                                       Sent by
=====================================  ==========================================  ===================================
evilflowers_image.figures              ``IMAGE_QUEUE``                             analyzer (kwargs, ``RegionsJob``)
evilflowers_image.standalone.figures   ``evilflowers_image.standalone`` and        books digitalizer
                                       ``evilflowers_image.standalone.interactive``  (``StandaloneFiguresJob``)
=====================================  ==========================================  ===================================

One image, two Deployments. The catalog one consumes ``IMAGE_QUEUE`` on the catalog's Redis db. With
``IMAGE_STANDALONE=1`` the worker consumes the two standalone queues instead (interactive first), on the
digitalizer's db, and needs no catalog key; an interactive-only replica narrows them with ``-Q``.

Everything else is evilflowers-worker's ``create_app``: late acknowledgement, prefetch 1, the db-wide visibility
timeout, the scale-in protocol on SIGTERM, the delivery cap, telemetry and JSON logs. No result backend: the catalog
job reports to the catalog, the standalone job writes an outcome file and its sender attached ``link`` callbacks.
"""

from evilflowers_worker.runtime import create_app

from evilflowers_image.settings import get_settings

#: A standalone job's run and job are the digitalizer's, not an extraction run (span attribute names).
STANDALONE_ATTRIBUTES = {
    "run_id": "evilflowers.digitalizer.run_id",
    "job_id": "evilflowers.digitalizer.job_id",
    "delivery": "evilflowers.digitalizer.delivery",
}

settings = get_settings()
app = create_app(
    "image",
    settings,
    include=["evilflowers_image.tasks"],
    queues=settings.queues(),
    routes={"evilflowers_image.standalone.*": settings.standalone_queue} if settings.standalone else None,
    attributes=STANDALONE_ATTRIBUTES if settings.standalone else None,
)
