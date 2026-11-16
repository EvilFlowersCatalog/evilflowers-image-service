from pathlib import Path

import pymupdf
import pytest
from evilflowers_worker.contract import Box, LayoutRegion
from evilflowers_worker.judges import DeciderClient, Judges, Thresholds
from PIL import Image, ImageDraw

from evilflowers_image.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Defaults only (no `.env`), storage in a temporary directory, no retry sleeps worth waiting for."""
    return Settings(_env_file=None, storage_path=tmp_path, catalog_attempts=1, image_tag="test")


def write_pdf(path) -> None:
    """A 600 x 800 pt page, a filled rectangle from (100, 100) to (400, 400)."""
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(pymupdf.Rect(100, 100, 400, 400), color=(1, 0, 0), fill=(0, 0, 1))
    document.save(path)


@pytest.fixture
def pdf(settings) -> str:
    """`doc.pdf` under the storage root (`write_pdf`)."""
    write_pdf(settings.storage_path / "doc.pdf")
    return "doc.pdf"


#: The rectangle of `pdf` as page fractions.
FIGURE_BOX = {"x0": 1 / 6, "y0": 0.125, "x1": 2 / 3, "y1": 0.5}


def region(page: int = 1, seq: int = 1, bbox: dict | None = None, caption: str | None = None) -> LayoutRegion:
    return LayoutRegion(page=page, seq=seq, bbox=Box(**(bbox or FIGURE_BOX)), caption=caption)


# -- Patterned figures: a flat box has no perceptual hash ------------------------------------------------------------

#: A logo (stripes) at the top left of a 600 x 800 pt page, and a chart (bars) below it, as page fractions.
LOGO_BOX = {"x0": 0.1, "y0": 0.05, "x1": 0.3, "y1": 0.15}
CHART_BOX = {"x0": 1 / 6, "y0": 0.375, "x1": 5 / 6, "y1": 0.875}


def _logo(draw, x0: float, y0: float, x1: float, y1: float) -> None:
    step = (y1 - y0) / 6
    for band in range(6):
        draw((x0, y0 + band * step, x1, y0 + (band + 1) * step), (0, 0, 0) if band % 2 else (0.9, 0.2, 0.1))


def _chart(draw, x0: float, y0: float, x1: float, y1: float, variant: int) -> None:
    width = (x1 - x0) / 8
    for bar in range(8):
        height = (y1 - y0) * (((bar * (variant + 3)) % 7) + 1) / 8
        draw((x0 + bar * width, y1 - height, x0 + (bar + 0.6) * width, y1), (0.1, 0.3, 0.8))


def write_pages_pdf(path, pages: int = 3) -> None:
    """``pages`` 600 x 800 pt pages, each with the same logo (``LOGO_BOX``) and a different chart (``CHART_BOX``)."""
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page(width=600, height=800)

        def rect(box, colour, page=page):
            page.draw_rect(pymupdf.Rect(*box), color=None, fill=colour)

        _logo(rect, 60, 40, 180, 120)
        _chart(rect, 100, 300, 500, 700, number)
    document.save(path)


def write_leaf(path: Path, variant: int, dpi: int | None = 300) -> None:
    """A leaf image the size of a 600 x 800 pt page at ``dpi`` (pixels as if at 300 without metadata), with the
    logo and chart of ``write_pages_pdf``."""
    scale = 300 / 72
    image = Image.new("RGB", (round(600 * scale), round(800 * scale)), "white")
    canvas = ImageDraw.Draw(image)

    def rect(box, colour):
        canvas.rectangle([value * scale for value in box], fill=tuple(round(channel * 255) for channel in colour))

    _logo(rect, 60, 40, 180, 120)
    _chart(rect, 100, 300, 500, 700, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    if dpi:
        image.save(path, dpi=(dpi, dpi))
    else:
        image.save(path)


# -- decider-vision, faked at the HTTP level --------------------------------------------------------------------------


class Response:
    def __init__(self, status: int, body: dict):
        self.status_code, self.body = status, body
        self.ok = status < 400
        self.text = str(body)

    def json(self):
        return self.body


class FakeDecider:
    """``POST /v1/systemone``: answers ``choose(call_number)`` → ``(choice, p)``, or raises ``error``."""

    MODEL = "strands-decider-2B-qwen3.5-v1-2610"

    def __init__(self, choose=lambda _number: ("chart", 0.97), error: Exception | None = None, status: int = 200):
        self.choose, self.error, self.status, self.calls = choose, error, status, []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        if self.error is not None:
            raise self.error
        choice, p = self.choose(len(self.calls))
        answer = {"choice": choice, "probabilities": {choice: p}, "confidence": p}
        return Response(self.status, {"answers": {"figure_kind": answer}, "model": self.MODEL})


def judges(settings: Settings, decider: FakeDecider | None, thresholds: Thresholds | None = None) -> Judges:
    """``Judges`` with only decider-vision, on ``decider``'s fake HTTP (``None``: no decider configured)."""
    if thresholds is not None:
        settings = settings.model_copy(update={"judge_thresholds": {"figure_kind": thresholds}})
    client = None
    if decider is not None:
        client = DeciderClient(
            "decider-vision", "http://decider-vision", vision=True, timeout=5, http=decider, revision="2610"
        )
    return Judges(decider=None, decider_vision=client, ollama=None, rerank=None, settings=settings)
