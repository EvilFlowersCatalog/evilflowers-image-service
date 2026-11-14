"""Safe scale-in on a real Redis: a SIGTERMed worker hands its unacknowledged task back to the queue.

Runs a prefork worker as a subprocess (signal handlers and pool termination are not exercised in-process).
Needs Redis: `TEST_REDIS_URL` (CI sets it, and then a broker that is down fails the test), otherwise
redis://localhost:6379/15, skipped when nothing answers there.
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import redis

SOFT_TIMEOUT = 2.0
TESTS_DIR = Path(__file__).parent
SRC_DIR = TESTS_DIR.parent / "src"


@pytest.fixture(scope="module")
def redis_url() -> str:
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        return url
    url = "redis://localhost:6379/15"
    try:
        redis.Redis.from_url(url, socket_connect_timeout=1).ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("no Redis at localhost:6379 (set TEST_REDIS_URL)")
    return url


@pytest.fixture
def broker(redis_url):
    client = redis.Redis.from_url(redis_url)
    queue = f"test_shutdown_{uuid.uuid4().hex}"
    yield client, queue
    client.delete(queue)


def _start_worker(redis_url: str, queue: str, *, remap: bool) -> subprocess.Popen:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(TESTS_DIR), str(SRC_DIR)]),
        "REDIS_URL": redis_url,
        "IMAGE_QUEUE": queue,
        "WORKER_SOFT_SHUTDOWN_TIMEOUT": str(SOFT_TIMEOUT),
        "LOG_FORMAT": "text",
    }
    env.pop("REMAP_SIGTERM", None)
    if remap:
        env["REMAP_SIGTERM"] = "SIGQUIT"
    return subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "shutdown_app", "worker", "--pool=prefork", "--concurrency=1",
         f"--queues={queue}", "--loglevel=INFO", "--without-gossip", "--without-mingle", "--without-heartbeat"],
        env=env,
        cwd=TESTS_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )  # fmt: skip


def _send(redis_url: str, queue: str, marker: Path) -> str:
    from celery import Celery

    sender = Celery(broker=redis_url)
    sender.conf.broker_connection_retry_on_startup = True
    result = sender.send_task("shutdown_app.slow", kwargs={"marker": str(marker)}, queue=queue)
    return result.id


def _wait_for(condition, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.1)


def _queued_ids(client: redis.Redis, queue: str) -> list[str]:
    return [json.loads(raw)["headers"]["id"] for raw in client.lrange(queue, 0, -1)]


def _unacked_ids(client: redis.Redis) -> list[str]:
    return [json.loads(raw)[0]["headers"]["id"] for raw in client.hvals("unacked")]


def _output(worker: subprocess.Popen) -> str:
    return worker.stdout.read().decode(errors="replace") if worker.stdout else ""


def test_sigterm_mid_task_puts_the_task_back_in_the_queue(redis_url, broker, tmp_path):
    client, queue = broker
    marker = tmp_path / "started"
    worker = _start_worker(redis_url, queue, remap=True)
    try:
        task_id = _send(redis_url, queue, marker)
        _wait_for(marker.exists, 60, "the task to start")
        assert _queued_ids(client, queue) == []
        assert task_id in _unacked_ids(client)

        started = time.monotonic()
        worker.send_signal(signal.SIGTERM)
        worker.wait(timeout=SOFT_TIMEOUT + 15)
        elapsed = time.monotonic() - started
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait()

    output = _output(worker)
    assert elapsed < SOFT_TIMEOUT + 10, output
    assert _queued_ids(client, queue) == [task_id], output
    assert task_id not in _unacked_ids(client), output


def test_without_the_remap_sigterm_waits_for_the_task(redis_url, broker, tmp_path):
    """Why the image sets REMAP_SIGTERM: plain SIGTERM is a warm shutdown that ignores the soft timeout."""
    client, queue = broker
    marker = tmp_path / "started"
    worker = _start_worker(redis_url, queue, remap=False)
    child = None
    try:
        task_id = _send(redis_url, queue, marker)
        _wait_for(marker.exists, 60, "the task to start")
        child = int(marker.read_text())

        worker.send_signal(signal.SIGTERM)
        time.sleep(SOFT_TIMEOUT + 3)
        assert worker.poll() is None, "warm shutdown should still be waiting for the task"
        assert _queued_ids(client, queue) == []
        assert task_id in _unacked_ids(client)
    finally:
        worker.kill()
        worker.wait()
        if child:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
        # Do not leave the message for the next run's restore.
        for tag, raw in client.hgetall("unacked").items():
            if json.loads(raw)[0]["headers"]["id"] == task_id:
                client.hdel("unacked", tag)
                client.zrem("unacked_index", tag)
