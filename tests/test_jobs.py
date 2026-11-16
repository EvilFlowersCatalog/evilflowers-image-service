"""``FiguresJob`` in process, against the kit's ``FakeCatalog``: what it posts and how it reports."""

import pytest
from evilflowers_worker.catalog import RunSuperseded
from evilflowers_worker.contract import RegionsJob
from evilflowers_worker.judges import Thresholds
from evilflowers_worker.testing import FakeCatalog, RefusingCatalog, running

from conftest import FIGURE_BOX, FakeDecider, judges
from evilflowers_image.jobs import FiguresJob

REGIONS = [{"page": 1, "seq": 1, "bbox": FIGURE_BOX, "caption": "Fig. 1"}]


def pending(job: str = "figures", attempt: int | None = None) -> FakeCatalog:
    return FakeCatalog(states=[running(jobs={job: "pending"}, attempt=attempt)])


def job(settings, catalog, source="doc.pdf", regions=REGIONS, delivery=1, **message) -> FiguresJob:
    kwargs = {"run_id": "run-1", "source": source, "output_dir": "runs/run-1/v1", "regions": regions, **message}
    return FiguresJob(RegionsJob.model_validate(kwargs), settings=settings, catalog=catalog, delivery=delivery)


def test_done_posts_the_figures_then_the_job(settings, pdf):
    catalog = pending()
    assert job(settings, catalog).run() == "done"
    assert [region["image_path"] for region in catalog.regions_posted] == ["runs/run-1/v1/p001-fig01.webp"]
    [report] = catalog.jobs
    assert report["name"] == "figures" and report["status"] == "done"
    assert report["provenance"] == {"image": "test", "crop_dpi": 144}


def test_a_batch_reports_under_its_own_job(settings, pdf):
    catalog = pending("figures:0001-0008", attempt=3)
    assert job(settings, catalog, job="figures:0001-0008", attempt=3).run() == "done"
    assert [report["name"] for report in catalog.jobs] == ["figures:0001-0008"]


def test_an_empty_batch_still_reports_done_without_opening_the_pdf(settings):
    catalog = pending("figures:0009-0016")
    assert job(settings, catalog, source="missing.pdf", regions=[], job="figures:0009-0016").run() == "done"
    assert catalog.regions_posted == []
    assert [(report["name"], report["status"]) for report in catalog.jobs] == [("figures:0009-0016", "done")]


@pytest.mark.parametrize(
    ("state", "outcome"),
    [
        (running(jobs={"figures": "done"}), "already_done"),
        (running(jobs={"figures": "pending"}, status="finished"), "not_running"),
        (running(jobs={"figures": "pending"}, attempt=4), "superseded"),
    ],
)
def test_the_run_is_read_before_the_work(settings, pdf, state, outcome):
    catalog = FakeCatalog(states=[state])
    assert job(settings, catalog, attempt=3).run() == outcome
    assert catalog.regions_posted == []
    assert not (settings.storage_path / "runs").exists()
    assert [report["status"] for report in catalog.jobs] == (["superseded"] if outcome == "superseded" else [])


def test_the_decision_fields_reach_the_catalog(settings, pdf):
    catalog = pending()
    decider = FakeDecider(choose=lambda _n: ("stamp", 0.95))
    message = {"run_id": "run-1", "source": pdf, "output_dir": "runs/run-1/v1", "regions": REGIONS}
    figures = FiguresJob(
        RegionsJob.model_validate(message),
        settings=settings,
        catalog=catalog,
        delivery=1,
        judges=judges(settings, decider, Thresholds(keep=0.8, hide=0.9)),
    )
    assert figures.run() == "done"
    [posted] = catalog.regions_posted
    assert {key: posted[key] for key in ("band", "p", "decision", "decider_model", "category")} == {
        "band": "hide",
        "p": 0.95,
        "decision": "stamp",
        "decider_model": f"{FakeDecider.MODEL}@2610",
        "category": "stamp",
    }


def test_judges_off_post_no_decision_fields(settings, pdf):
    catalog = pending()
    assert job(settings, catalog).run() == "done"
    [posted] = catalog.regions_posted
    assert not {"band", "p", "decision", "decider_model"} & posted.keys()


def test_captions_enabled_records_the_model(settings, pdf):
    settings = settings.model_copy(update={"captions_enabled": True})
    assert job(settings, pending()).provenance()["caption_model"] == "qwen2.5vl:7b"


def test_an_unreadable_pdf_fails_the_job(settings):
    catalog = pending()
    assert job(settings, catalog, source="missing.pdf").run() == "failed"
    [report] = catalog.jobs
    assert report["name"] == "figures" and report["status"] == "failed" and report["error"]
    assert catalog.regions_posted == []


def test_an_output_dir_outside_the_storage_fails_the_job(settings, pdf):
    catalog = pending()
    assert job(settings, catalog, output_dir="../elsewhere").run() == "failed"
    [report] = catalog.jobs
    assert report["status"] == "failed" and "STORAGE_PATH" in report["error"]


def test_a_refused_run_stops_quietly(settings, pdf):
    catalog = RefusingCatalog(states=[running(jobs={"figures": "pending"})])
    assert job(settings, catalog).run() == "not_running"
    assert catalog.jobs == []


def test_a_superseded_write_is_final(settings, pdf):
    catalog = FakeCatalog(states=[running(jobs={"figures": "pending"})], fail_on={"regions": RunSuperseded("x")})
    assert job(settings, catalog).run() == "superseded"
    assert [report["status"] for report in catalog.jobs] == ["superseded"]


def test_a_failing_catalog_is_still_reported(settings, pdf):
    catalog = FakeCatalog(states=[running(jobs={"figures": "pending"})], fail_on={"regions": ConnectionError("down")})
    assert job(settings, catalog).run() == "failed"
    assert [report["status"] for report in catalog.jobs] == ["failed"]


def test_past_the_delivery_cap_the_job_is_failed_without_the_work(settings, pdf):
    catalog = pending()
    assert job(settings, catalog, delivery=settings.max_deliveries + 1).run() == "failed"
    assert catalog.reads == 0 and catalog.regions_posted == []
    [report] = catalog.jobs
    assert report["error"].startswith(f"Gave up after {settings.max_deliveries} deliveries")


def test_a_failed_job_marks_its_span(settings):
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    tracer = sdk.TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("run/evilflowers_image.figures") as span:
        job(settings, pending(), source="missing.pdf").run()
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["evilflowers.extraction.job"] == "figures"
