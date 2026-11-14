"""A worker with the real `CeleryConfig` and one slow task, for `test_shutdown.py` (run as a subprocess).

The broker, queue and soft timeout come from the environment, as in a pod.
"""

import os
import time
from pathlib import Path

from celery import Celery

from evilflowers_image.settings import Settings
from evilflowers_image.worker import CeleryConfig

app = Celery("shutdown_app")
app.config_from_object(CeleryConfig(Settings(_env_file=None)))


@app.task(name="shutdown_app.slow")
def slow(marker: str) -> None:
    """Stands in for a book: tells the test it started, then runs far longer than the test waits."""
    Path(marker).write_text(str(os.getpid()))
    time.sleep(300)
