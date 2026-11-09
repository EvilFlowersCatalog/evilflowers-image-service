import pymupdf
import pytest

from evilflowers_image.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Defaults only (no `.env`), storage in a temporary directory, no retry sleeps worth waiting for."""
    return Settings(_env_file=None, storage_path=tmp_path, catalog_attempts=1, image_tag="test")


@pytest.fixture
def pdf(settings) -> str:
    """`doc.pdf` under the storage root: a 600 x 800 pt page, a filled rectangle from (100, 100) to (400, 400)."""
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(pymupdf.Rect(100, 100, 400, 400), color=(1, 0, 0), fill=(0, 0, 1))
    document.save(settings.storage_path / "doc.pdf")
    return "doc.pdf"


#: The rectangle of `pdf` as page fractions.
FIGURE_BOX = {"x0": 1 / 6, "y0": 0.125, "x1": 2 / 3, "y1": 0.5}


class FakeCatalog:
    """Records what a job sends; `refuse` makes every call answer 409, `broken` raise."""

    def __init__(self, refuse: bool = False, broken: bool = False):
        self.refuse, self.broken = refuse, broken
        self.regions_sent: list[dict] = []
        self.jobs: list[tuple[str, dict]] = []

    def _check(self):
        from evilflowers_image.clients.catalog import RunNotRunning

        if self.refuse:
            raise RunNotRunning("finished")
        if self.broken:
            raise ConnectionError("catalog down")

    def regions(self, regions):
        self._check()
        self.regions_sent.extend(regions)

    def job(self, name, **report):
        self.jobs.append((name, report))
        self._check()
