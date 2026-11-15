"""Page geometry and crops shared by the region services (IP-018).

Boxes arrive as page fractions with a top-left origin on the original file's
1-based page, the same convention PyMuPDF uses for page coordinates. Crops are
written as WebP into the run's folder under the shared storage mount.
"""

import io
from pathlib import Path

import pymupdf
from evilflowers_worker.contract import Box
from evilflowers_worker.outcome import atomic_write
from PIL import Image


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
