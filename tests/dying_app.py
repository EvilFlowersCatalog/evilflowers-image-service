"""The real worker app, except that reading the figures kills the process (an OOM, as far as the parent can tell).

For ``test_end_to_end``'s delivery cap: ``celery -A dying_app worker`` with ``tests/`` on ``PYTHONPATH``. A forked pool
child (Linux) inherits the patch from the parent; a spawned one (macOS) imports this module again through ``include``.
"""

import os
import signal

from evilflowers_image import figures
from evilflowers_image.worker import app

__all__ = ["app"]


def _die(*_args, **_kwargs):
    os.kill(os.getpid(), signal.SIGKILL)


figures.FigureReader.read = _die
app.conf.include = [*app.conf.include, __name__]
