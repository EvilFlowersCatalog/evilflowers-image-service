import pymupdf
import pytest
from evilflowers_worker.contract import Box, LayoutRegion

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
