import os

import fitz
import pytest

import captions
import crops
import settings
import worker


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(100, 100, 400, 400), color=(1, 0, 0), fill=(0, 0, 1))
    pdf.save(tmp_path / "doc.pdf")
    return tmp_path


def test_gates():
    box = {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}
    assert worker.gate(box, (300, 300)) is None
    assert worker.gate(box, (50, 300)) == "too small"
    assert worker.gate(box, (2000, 100)) == "extreme aspect ratio"
    assert worker.gate({"x0": 0, "y0": 0, "x1": 1, "y1": 0.95}, (900, 900)) == "covers the page"


def test_crop_is_written_where_the_catalog_expects_it(storage):
    with fitz.open(storage / "doc.pdf") as document:
        region = {"page": 1, "seq": 3, "bbox": {"x0": 1 / 6, "y0": 0.125, "x1": 2 / 3, "y1": 0.5}, "caption": "Fig. 1"}
        result = worker._figure(document, region, "catalogs/c/e/extraction/a/v1")
    assert result["image_path"] == "catalogs/c/e/extraction/a/v1/p001-fig03.webp"
    assert result["caption"] == "Fig. 1"
    assert os.path.exists(storage / result["image_path"])


def test_caption_answer_parsing():
    assert captions.parse('{"caption": "A bar chart.", "category": "Chart"}') == ("A bar chart.", "chart")
    assert captions.parse('Sure! {"caption": "x", "category": "poster"}') == ("x", "other")
    assert captions.parse("no json") == (None, None)
    assert "{" in captions.PROMPT.format(caption="")


def test_rect_uses_top_left_origin():
    page = fitz.open().new_page(width=200, height=100)
    assert crops.rect({"x0": 0, "y0": 0, "x1": 0.5, "y1": 0.5}, page) == fitz.Rect(0, 0, 100, 50)
