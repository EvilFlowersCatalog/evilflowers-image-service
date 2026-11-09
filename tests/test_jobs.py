from conftest import FIGURE_BOX, FakeCatalog
from evilflowers_image.jobs import FiguresJob

REGIONS = [{"page": 1, "seq": 1, "bbox": FIGURE_BOX, "caption": "Fig. 1"}]


def job(settings, source, catalog, regions=REGIONS):
    return FiguresJob("run-1", source, "runs/run-1/v1", regions, settings=settings, catalog=catalog)


def test_done_posts_the_figures_then_the_job(settings, pdf):
    catalog = FakeCatalog()
    assert job(settings, pdf, catalog).run() == "done"
    assert [region["image_path"] for region in catalog.regions_sent] == ["runs/run-1/v1/p001-fig01.webp"]
    assert catalog.jobs == [("figures", {"status": "done", "provenance": {"image": "test", "crop_dpi": 144}})]


def test_captions_enabled_records_the_model(settings, pdf):
    settings = settings.model_copy(update={"captions_enabled": True})
    assert job(settings, pdf, FakeCatalog()).provenance()["caption_model"] == "qwen2.5vl:7b"


def test_an_unreadable_pdf_fails_the_job(settings):
    catalog = FakeCatalog()
    assert job(settings, "missing.pdf", catalog).run() == "failed"
    [(name, report)] = catalog.jobs
    assert name == "figures" and report["status"] == "failed" and report["error"]
    assert catalog.regions_sent == []


def test_a_refused_run_stops_quietly(settings, pdf):
    catalog = FakeCatalog(refuse=True)
    assert job(settings, pdf, catalog).run() == "not_running"
    assert catalog.jobs == []


def test_a_failing_catalog_is_still_reported(settings, pdf):
    catalog = FakeCatalog(broken=True)
    assert job(settings, pdf, catalog).run() == "failed"
    assert [report["status"] for _, report in catalog.jobs] == ["failed"]
