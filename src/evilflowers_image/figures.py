"""From the analyzer's figure regions to the regions the catalog ingests.

For each region: render the box at ``CROP_DPI``, drop it when it fails a gate,
write the WebP crop, and optionally ask the captioner for a description and a
category. A region that fails is logged and skipped; only a document that
cannot be opened fails the job.
"""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import pymupdf
from PIL import Image

from evilflowers_image import crops
from evilflowers_image.observability import metrics
from evilflowers_image.settings import Settings, get_settings

logger = logging.getLogger(__name__)

KIND = "figure"


class Captioner(Protocol):
    model: str

    def describe(self, image: Image.Image, printed_caption: str | None) -> tuple[str | None, str | None]: ...


def gate(box: Mapping[str, float], size_px: tuple[int, int], settings: Settings) -> str | None:
    """Why a region is not kept as a figure, or None."""
    width, height = size_px
    if min(width, height) < settings.min_side_px:
        return "too small"
    if max(width, height) / max(min(width, height), 1) > settings.max_aspect_ratio:
        return "extreme aspect ratio"
    if crops.coverage(box) > settings.max_page_coverage:
        return "covers the page"
    return None


class FigureReader:
    def __init__(self, settings: Settings | None = None, captioner: Captioner | None = None):
        self.settings = settings or get_settings()
        self.captioner = captioner

    def read(self, path: Path, output_dir: str, regions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """The kept figures. Raises only when the document cannot be opened."""
        kept = []
        with pymupdf.open(path) as document:
            for region in regions:
                try:
                    figure = self.figure(document, region, output_dir)
                except Exception:
                    logger.exception("Figure on page %s skipped", region.get("page"))
                    metrics.record_region("error")
                    continue
                if figure is not None:
                    kept.append(figure)
        return kept

    def figure(self, document: pymupdf.Document, region: Mapping[str, Any], output_dir: str) -> dict[str, Any] | None:
        page = document[region["page"] - 1]
        image = crops.render(page, crops.rect(region["bbox"], page), self.settings.crop_dpi)
        if reason := gate(region["bbox"], image.size, self.settings):
            logger.info("Figure on page %s dropped: %s", region["page"], reason)
            metrics.record_region(reason)
            return None

        name = crops.crop_name(output_dir, region["page"], "fig", region["seq"])
        crops.save(image, self.settings.storage_path, name, self.settings.webp_quality)

        printed_caption = region.get("caption")
        description, category, provenance = None, None, {}
        if self.captioner is not None:
            try:
                description, category = self.captioner.describe(image, printed_caption)
                provenance = {"caption_model": self.captioner.model}
            except Exception:
                # The crop and its position are still worth keeping without a description.
                logger.exception("Caption failed for the figure on page %s", region["page"])
        metrics.record_region("kept")

        return {
            "kind": KIND,
            "page": region["page"],
            "seq": region["seq"],
            "bbox": region["bbox"],
            "image_path": name,
            # The document's own caption and the model's description travel apart
            # (IP-018 Phase 8); `caption` is kept for catalogs that predate them.
            "caption": printed_caption or description,
            "printed_caption": printed_caption,
            "description": description,
            "category": category,
            "provenance": provenance,
        }
