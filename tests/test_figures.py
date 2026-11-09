import pymupdf
import pytest
from PIL import Image

from conftest import FIGURE_BOX
from evilflowers_image import captions, crops
from evilflowers_image.figures import FigureReader, gate


class FakeCaptioner:
    model = "fake-vl"

    def __init__(self, answer=("A blue square.", "drawing"), error: Exception | None = None):
        self.answer, self.error, self.calls = answer, error, []

    def describe(self, image, printed_caption):
        self.calls.append((image.size, printed_caption))
        if self.error:
            raise self.error
        return self.answer


def test_gates(settings):
    box = {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}
    assert gate(box, (300, 300), settings) is None
    assert gate(box, (50, 300), settings) == "too small"
    assert gate(box, (2000, 100), settings) == "extreme aspect ratio"
    assert gate({"x0": 0, "y0": 0, "x1": 1, "y1": 0.95}, (900, 900), settings) == "covers the page"


def test_rect_uses_top_left_origin():
    page = pymupdf.open().new_page(width=200, height=100)
    assert crops.rect({"x0": 0, "y0": 0, "x1": 0.5, "y1": 0.5}, page) == pymupdf.Rect(0, 0, 100, 50)


def test_crop_name():
    assert crops.crop_name("runs/a/v1/", 12, "fig", 3) == "runs/a/v1/p012-fig03.webp"


def test_crop_is_written_where_the_catalog_expects_it(settings, pdf):
    region = {"page": 1, "seq": 3, "bbox": FIGURE_BOX, "caption": "Fig. 1"}
    [figure] = FigureReader(settings).read(settings.source_path(pdf), "catalogs/c/e/extraction/a/v1", [region])
    assert figure["image_path"] == "catalogs/c/e/extraction/a/v1/p001-fig03.webp"
    assert (settings.storage_path / figure["image_path"]).exists()
    assert figure["kind"] == "figure" and figure["bbox"] == FIGURE_BOX
    assert figure["caption"] == figure["printed_caption"] == "Fig. 1"
    assert figure["description"] is None and figure["category"] is None and figure["provenance"] == {}


def test_dropped_and_broken_regions_are_skipped(settings, pdf):
    regions = [
        {"page": 1, "seq": 1, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.12, "y1": 0.12}},  # too small
        {"page": 9, "seq": 2, "bbox": FIGURE_BOX},  # no such page
        {"page": 1, "seq": 3, "bbox": FIGURE_BOX},
    ]
    kept = FigureReader(settings).read(settings.source_path(pdf), "out", regions)
    assert [figure["seq"] for figure in kept] == [3]


def test_an_unreadable_pdf_raises(settings):
    (settings.storage_path / "broken.pdf").write_bytes(b"not a pdf")
    with pytest.raises(Exception):  # noqa: B017 - whatever PyMuPDF raises fails the job
        FigureReader(settings).read(settings.source_path("broken.pdf"), "out", [])


def test_the_description_travels_apart_from_the_printed_caption(settings, pdf):
    captioner = FakeCaptioner()
    region = {"page": 1, "seq": 1, "bbox": FIGURE_BOX, "caption": None}
    [figure] = FigureReader(settings, captioner).read(settings.source_path(pdf), "out", [region])
    assert captioner.calls[0][1] is None
    assert figure["printed_caption"] is None
    assert figure["description"] == figure["caption"] == "A blue square."
    assert figure["category"] == "drawing"
    assert figure["provenance"] == {"caption_model": "fake-vl"}


def test_a_failing_caption_keeps_the_crop(settings, pdf):
    region = {"page": 1, "seq": 1, "bbox": FIGURE_BOX, "caption": "Fig. 2"}
    reader = FigureReader(settings, FakeCaptioner(error=TimeoutError("ollama")))
    [figure] = reader.read(settings.source_path(pdf), "out", [region])
    assert figure["caption"] == "Fig. 2" and figure["description"] is None and figure["provenance"] == {}


def test_caption_answer_parsing():
    assert captions.parse('{"caption": "A bar chart.", "category": "Chart"}') == ("A bar chart.", "chart")
    assert captions.parse('Sure! {"caption": "x", "category": "poster"}') == ("x", "other")
    assert captions.parse("no json") == (None, None)
    assert captions.parse("[1, 2]") == (None, None)
    assert "{" in captions.PROMPT.format(caption="")


def test_ollama_request(settings):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"caption": "A map.", "category": "map"}'}}

    class Http:
        def post(self, url, json, timeout):
            self.sent = (url, json, timeout)
            return Response()

    http = Http()
    image = Image.new("RGB", (3000, 1500))
    result = captions.OllamaCaptioner(settings, http).describe(image, "Fig. 3")
    url, payload, timeout = http.sent
    assert result == ("A map.", "map")
    assert url == settings.ollama_endpoint and timeout == settings.caption_timeout
    assert payload["model"] == settings.caption_model and payload["format"] == "json" and not payload["stream"]
    assert 'printed caption is: "Fig. 3"' in payload["messages"][0]["content"]
