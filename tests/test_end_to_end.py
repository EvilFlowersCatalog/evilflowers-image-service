"""A real prefork worker (``evilflowers_worker.testing.WorkerProcess``) against Redis and a stub catalog.

What the analyzer and the catalog see on the wire: the job name the task reports under (a batch or ``figures``),
``?attempt=`` on every write, an empty batch that still reports, and a book that kills its worker ending ``failed``
after ``MAX_DELIVERIES`` instead of looping forever.

Needs ``TEST_REDIS_URL`` (default ``redis://localhost:6379/15``); skipped when no Redis answers, except in CI (``CI``
set), where a missing Redis is a failure.
"""

import os
from pathlib import Path

import pytest
from evilflowers_worker.testing import StubCatalogServer, WorkerProcess, redis_client, wait_for

from conftest import FIGURE_BOX, write_pdf

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
HERE = Path(__file__).parent
RUN = "/extraction/v1/runs/run-1"


@pytest.fixture
def broker():
    if redis_client(REDIS_URL) is None:
        if os.environ.get("CI"):
            pytest.fail(f"no Redis at {REDIS_URL}: the real-worker tests must run in CI")
        pytest.skip(f"no Redis at {REDIS_URL}")
    return REDIS_URL


@pytest.fixture
def storage(tmp_path) -> Path:
    write_pdf(tmp_path / "doc.pdf")
    return tmp_path


@pytest.fixture
def worker(broker, storage):
    """``worker(app, **env)``: a running worker of ``app`` reporting to ``CATALOG_API_URL``."""
    started: list[WorkerProcess] = []

    def make(catalog: StubCatalogServer, app: str = "evilflowers_image.worker", **env: str) -> WorkerProcess:
        environment = {"STORAGE_PATH": str(storage), "CATALOG_API_URL": catalog.url, "CATALOG_ATTEMPTS": "1", **env}
        process = WorkerProcess(app, redis_url=broker, pythonpath=[str(HERE)], env=environment).__enter__()
        started.append(process)
        process.wait_ready()
        return process

    yield make
    for process in started:
        process.__exit__(None, None, None)


def figures(process: WorkerProcess, **kwargs) -> None:
    message = {"run_id": "run-1", "source": "doc.pdf", "output_dir": "runs/run-1/v1", **kwargs}
    process.send("evilflowers_image.figures", **message)


def reported(catalog: StubCatalogServer) -> bool:
    return any("/jobs/" in path for _method, path in catalog.paths())


def test_a_batch_reports_under_its_job_with_the_attempt(worker, storage):
    run = {"status": "running", "jobs": {"figures:0001-0008": "pending"}, "attempt": 3}
    with StubCatalogServer(run=run) as catalog:
        process = worker(catalog)
        regions = [{"page": 1, "seq": 1, "bbox": FIGURE_BOX, "caption": "Fig. 1"}]
        figures(process, job="figures:0001-0008", attempt=3, regions=regions)
        assert wait_for(lambda: reported(catalog), 60), catalog.calls

    assert catalog.paths() == [
        ("GET", RUN),
        ("POST", f"{RUN}/regions?attempt=3"),
        ("POST", f"{RUN}/jobs/figures:0001-0008?attempt=3"),
    ]
    [posted] = catalog.calls[1][2]["regions"]
    assert posted["image_path"] == "runs/run-1/v1/p001-fig01.webp"
    assert (storage / posted["image_path"]).is_file()
    assert catalog.calls[2][2]["status"] == "done"


def test_without_a_job_kwarg_it_reports_as_figures(worker):
    with StubCatalogServer(run={"status": "running", "jobs": {"figures": "pending"}, "attempt": 3}) as catalog:
        process = worker(catalog)
        figures(process, attempt=3, regions=[{"page": 1, "seq": 1, "bbox": FIGURE_BOX}])
        assert wait_for(lambda: reported(catalog), 60), catalog.calls

    assert catalog.paths()[-1] == ("POST", f"{RUN}/jobs/figures?attempt=3")


def test_an_empty_batch_reports_done(worker):
    run = {"status": "running", "jobs": {"figures:0009-0016": "pending"}, "attempt": 3}
    with StubCatalogServer(run=run) as catalog:
        process = worker(catalog)
        figures(process, job="figures:0009-0016", attempt=3, regions=[])
        assert wait_for(lambda: reported(catalog), 60), catalog.calls

    assert catalog.paths() == [("GET", RUN), ("POST", f"{RUN}/jobs/figures:0009-0016?attempt=3")]
    assert catalog.calls[1][2]["status"] == "done"


def test_a_book_that_kills_its_worker_ends_failed_after_the_cap(worker):
    with StubCatalogServer(run={"status": "running", "jobs": {"figures": "pending"}, "attempt": 3}) as catalog:
        process = worker(catalog, app="dying_app", MAX_DELIVERIES="2")
        before = process.unacked()
        figures(process, attempt=3, regions=[{"page": 1, "seq": 1, "bbox": FIGURE_BOX}])
        assert wait_for(lambda: reported(catalog), 120), catalog.calls
        # Acknowledged once reported: never delivered again.
        assert wait_for(lambda: process.redis.llen(process.queue) == 0 and process.unacked() == before, 30)

    # Deliveries 1 and 2 read the run and died; the third is past the cap and only reports.
    assert catalog.paths() == [("GET", RUN), ("GET", RUN), ("POST", f"{RUN}/jobs/figures?attempt=3")]
    report = catalog.calls[-1][2]
    assert report["status"] == "failed"
    assert report["error"].startswith("Gave up after 2 deliveries")
