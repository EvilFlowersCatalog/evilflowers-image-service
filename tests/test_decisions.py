"""Keep/hide (#6): the repeated-image check and decider-vision's category and band, through ``FigureReader``."""

import base64
import io

import pytest
from evilflowers_worker.judges import Thresholds
from PIL import Image, ImageDraw

from conftest import CHART_BOX, LOGO_BOX, FakeDecider, judges, region, write_pages_pdf
from evilflowers_image import decisions
from evilflowers_image.decisions import FIGURE_KIND, Fingerprint
from evilflowers_image.figures import FigureReader


@pytest.fixture
def book(settings) -> str:
    """Three pages, each with the same logo and its own chart."""
    write_pages_pdf(settings.storage_path / "book.pdf", pages=3)
    return "book.pdf"


def regions(pages: int = 3) -> list:
    """The logo (seq 1) and the chart (seq 2) of each page."""
    found = []
    for page in range(1, pages + 1):
        found += [region(page=page, seq=1, bbox=LOGO_BOX), region(page=page, seq=2, bbox=CHART_BOX)]
    return found


def read(settings, source, found, decider=None, captioner=None, thresholds=None):
    reader = FigureReader(settings, captioner, judges(settings, decider, thresholds) if decider else None)
    return reader.read(settings.source_path(source), "out", found)


def patterned(seed: int, size=(240, 160)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for index in range(8):
        x = (index * 29 * (seed + 1)) % size[0]
        draw.rectangle((x, 0, x + 12, size[1] * (index + 1) // 9), fill=(20 * index, 0, 200))
    return image


# -- the hash ------------------------------------------------------------------------------------------------------


def test_a_flat_crop_has_no_hash_and_never_repeats():
    flat = Image.new("RGB", (200, 100), (0, 0, 255))
    assert decisions.dhash(flat) is None
    fingerprints = [Fingerprint(page=page, hash=None, size=(200, 100)) for page in (1, 2, 3)]
    assert decisions.repeated(fingerprints, min_pages=3, max_distance=4) == set()


def test_the_same_image_at_another_scale_hashes_alike_and_another_image_does_not():
    image = patterned(1)
    same = decisions.dhash(image.resize((480, 320)))
    assert (decisions.dhash(image) ^ same).bit_count() <= 4
    assert (decisions.dhash(image) ^ decisions.dhash(patterned(2))).bit_count() > 4


def test_repeated_needs_enough_distinct_pages_and_a_similar_shape():
    logo = 0x0F0F_F0F0_1234_5678
    on = [Fingerprint(page=page, hash=logo, size=(200, 100)) for page in (1, 2)]
    assert decisions.repeated(on, min_pages=3, max_distance=4) == set()
    twice_on_one_page = [*on, Fingerprint(page=2, hash=logo, size=(200, 100))]
    assert decisions.repeated(twice_on_one_page, min_pages=3, max_distance=4) == set()
    third = [*on, Fingerprint(page=3, hash=logo ^ 0b111, size=(200, 100))]
    assert decisions.repeated(third, min_pages=3, max_distance=4) == {0, 1, 2}
    stretched = [*on, Fingerprint(page=3, hash=logo, size=(400, 100))]
    assert decisions.repeated(stretched, min_pages=3, max_distance=4) == set()


def test_the_question_is_the_contract_of_knowledge_64():
    assert FIGURE_KIND.id == "figure_kind"
    assert set(FIGURE_KIND.criteria) == {
        "chart", "diagram", "photo", "map", "table", "formula", "stamp", "decoration", "scan", "blank",
    }  # fmt: skip
    assert FIGURE_KIND.reject == {"stamp", "decoration", "scan", "blank"}


# -- through the reader ----------------------------------------------------------------------------------------------


def test_a_logo_on_every_page_is_hidden_without_asking_the_decider(settings, book):
    decider = FakeDecider()
    figures = read(settings, book, regions(), decider)

    logos = [figure for figure in figures if figure.seq == 1]
    charts = [figure for figure in figures if figure.seq == 2]
    assert [(logo.band, logo.decision, logo.p) for logo in logos] == [("hide", "repeated", None)] * 3
    assert all(logo.signals and len(logo.signals["dhash"]) == 16 for logo in logos)
    # Nothing is deleted: every crop is written and posted, hidden or not.
    assert all((settings.storage_path / figure.image_path).is_file() for figure in figures)
    # Only the three different charts went to the decider.
    assert len(decider.calls) == 3 and all(chart.decision == "chart" for chart in charts)


def test_two_pages_are_not_enough_to_hide(settings, book):
    decider = FakeDecider()
    figures = read(settings, book, regions(pages=2), decider)
    assert not any(figure.band == "hide" for figure in figures)
    assert len(decider.calls) == 4


def test_the_verdict_fills_the_catalog_fields_and_the_band_follows_the_thresholds(settings, book):
    thresholds = Thresholds(keep=0.8, hide=0.9)
    chart = [region(seq=2, bbox=CHART_BOX)]
    [figure] = read(settings, book, chart, FakeDecider(choose=lambda _n: ("stamp", 0.95)), thresholds=thresholds)
    assert (figure.band, figure.decision, figure.p, figure.category) == ("hide", "stamp", 0.95, "stamp")
    assert figure.decider_model == f"{FakeDecider.MODEL}@2610"
    assert figure.provenance["figure_kind"]["verdict"] == "stamp"

    [figure] = read(settings, book, chart, FakeDecider(choose=lambda _n: ("chart", 0.6)), thresholds=thresholds)
    assert (figure.band, figure.decision) == ("review", "chart")


def test_without_thresholds_the_catalog_gets_p_and_decision_but_no_band(settings, book):
    [figure] = read(settings, book, [region(seq=2, bbox=CHART_BOX)], FakeDecider(choose=lambda _n: ("photo", 0.7)))
    assert (figure.band, figure.decision, figure.p, figure.category) == (None, "photo", 0.7, "photo")


def test_the_decider_gets_the_contract_request(settings, book):
    decider = FakeDecider()
    read(settings, book, [region(seq=2, bbox=CHART_BOX)], decider)
    [(url, payload, timeout)] = decider.calls
    assert url == "http://decider-vision/v1/systemone" and timeout <= 5
    assert payload["state"] == decisions.STATE
    question = payload["questions"]["figure_kind"]
    assert question["type"] == "choice" and question["criteria"]["stamp"] == "stamp, signature or logo"
    [encoded] = payload["images"]
    image = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert image.format == "PNG" and max(image.size) <= settings.judge_max_side


@pytest.mark.parametrize(
    "decider",
    [
        FakeDecider(error=ConnectionError("down")),
        FakeDecider(status=503),
        FakeDecider(status=422),
        FakeDecider(choose=lambda _n: ("poster", 0.9)),
    ],
    ids=["unreachable", "5xx", "refused", "invalid"],
)
def test_a_decider_that_does_not_answer_leaves_the_region_unbanded(settings, book, decider):
    [figure] = read(settings, book, [region(seq=2, bbox=CHART_BOX, caption="Fig. 1")], decider)
    assert (figure.band, figure.p, figure.decision, figure.decider_model, figure.category) == (None,) * 5
    assert figure.caption == "Fig. 1" and "figure_kind" not in figure.provenance


def test_judges_off_ask_nothing_and_post_as_before(settings, book):
    [figure] = read(settings, book, [region(seq=2, bbox=CHART_BOX)], decider=None)
    assert figure.band is None and figure.provenance == {}
    [figure] = FigureReader(settings, judges=judges(settings, None)).read(
        settings.source_path(book), "out", [region(seq=2, bbox=CHART_BOX)]
    )
    assert figure.band is None and figure.provenance == {}


class Captioner:
    model = "fake-vl"

    def __init__(self):
        self.calls = 0

    def describe(self, image, printed_caption):
        self.calls += 1
        return "A bar chart.", "drawing"


def test_a_hidden_crop_is_not_described_and_the_deciders_category_wins(settings, book):
    captioner = Captioner()
    decider = FakeDecider(choose=lambda n: ("decoration", 0.99) if n == 1 else ("chart", 0.99))
    found = [region(page=1, seq=2, bbox=CHART_BOX), region(page=2, seq=2, bbox=CHART_BOX)]
    hidden, kept = read(settings, book, found, decider, captioner, thresholds=Thresholds(keep=0.8, hide=0.9))
    assert hidden.band == "hide" and hidden.description is None
    assert kept.band == "keep" and kept.description == "A bar chart." and kept.category == "chart"
    assert captioner.calls == 1 and kept.provenance["caption_model"] == "fake-vl"


def test_the_job_budget_stops_the_questions_not_the_job(settings, book):
    settings = settings.model_copy(update={"judge_budget_calls": 1})
    decider = FakeDecider()
    figures = read(settings, book, [region(page=page, seq=2, bbox=CHART_BOX) for page in (1, 2, 3)], decider)
    assert len(decider.calls) == 1
    assert [figure.decision for figure in figures] == ["chart", None, None]
