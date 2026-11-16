"""Page geometry, page sources and crops shared by both figures tasks (IP-018, #7).

Boxes arrive as page fractions with a top-left origin on a 1-based page, the same convention PyMuPDF uses for page
coordinates. A *page source* yields that page as a PyMuPDF page and the DPI to render it at:

- ``PdfPages``: the catalog task's PDF, page ``n`` of the document, at ``CROP_DPI``;
- ``LeafPages``: the standalone task's leaf images, page ``n`` is leaf ``n``. PyMuPDF opens an image as a one-page
  document sized by its DPI metadata (96 dpi without), and the render DPI is capped at the image's own so a crop is
  never upsampled.

Crops are written as WebP under the shared storage mount.
"""

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, Self

import pymupdf
from evilflowers_worker.contract import Box
from evilflowers_worker.outcome import atomic_write
from PIL import Image


class PageSource(Protocol):
    def page(self, number: int) -> tuple[pymupdf.Page, int]:
        """The 1-based page ``number`` and the DPI to render it at; raises when there is no such page."""
        ...


class PdfPages:
    """The pages of one PDF. Opening it raises when it cannot be read, which fails the job."""

    def __init__(self, path: Path, dpi: int):
        self.document = pymupdf.open(path)
        self.dpi = dpi

    def page(self, number: int) -> tuple[pymupdf.Page, int]:
        return self.document[number - 1], self.dpi

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.document.close()


class LeafPages:
    """Leaf images by leaf number, opened one at a time as a region asks for them.

    A leaf that cannot be read, or a file of more than one page (a PDF passed as a leaf), raises.
    """

    def __init__(self, leaves: Mapping[int, Path], dpi: int):
        self.leaves = dict(leaves)
        self.dpi = dpi
        self._open: tuple[int, pymupdf.Document, int] | None = None

    def page(self, number: int) -> tuple[pymupdf.Page, int]:
        if self._open is None or self._open[0] != number:
            self.close()
            if number not in self.leaves:
                raise KeyError(f"no leaf {number} in the message")
            path = self.leaves[number]
            document = pymupdf.open(path)
            if document.page_count != 1:
                document.close()
                raise ValueError(f"leaf {number} is not a single image: {path.name}")
            with Image.open(path) as image:
                native = image.width * 72 / document[0].rect.width
            self._open = (number, document, max(1, min(self.dpi, round(native))))
        _number, document, dpi = self._open
        return document[0], dpi

    def close(self) -> None:
        if self._open is not None:
            self._open[1].close()
            self._open = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def rect(box: Box, page: pymupdf.Page) -> pymupdf.Rect:
    """The box in the page's points."""
    width, height = page.rect.width, page.rect.height
    return pymupdf.Rect(box.x0 * width, box.y0 * height, box.x1 * width, box.y1 * height)


def coverage(box: Box) -> float:
    """Share of the page the box covers."""
    return max(box.x1 - box.x0, 0.0) * max(box.y1 - box.y0, 0.0)


def render(page: pymupdf.Page, clip: pymupdf.Rect, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(clip=clip, dpi=dpi, alpha=False)
    return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")


def crop_name(output_dir: str, page: int, kind: str, seq: int) -> str:
    """Storage name of a crop, relative to the storage root: `<output_dir>/p012-fig03.webp`."""
    return f"{output_dir.rstrip('/')}/p{page:03d}-{kind}{seq:02d}.webp"


def save(image: Image.Image, path: Path, quality: int) -> None:
    """Write the crop at ``path`` (checked by ``storage_file``); the catalog serves it and deletes it with the run.

    Atomic: a worker killed mid-write leaves no half crop behind, only a ``.partial`` the next write replaces.
    """
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=quality, method=4)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, buffer.getvalue())


def png(image: Image.Image, max_side: int) -> bytes:
    """The image as PNG, its longer side at most ``max_side`` (what a judge is sent; decider-vision scales to 448)."""
    image = image.copy()
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
