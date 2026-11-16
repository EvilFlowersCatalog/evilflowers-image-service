"""From the analyzer's figure regions to the regions a catalog or an orchestrator ingests (#6, #7).

Two passes over one job's regions:

1. **Crop.** Render the box at ``CROP_DPI``, drop it when it fails a gate, write the WebP crop and hash it.
2. **Decide.** Crops repeated on ``REPEAT_MIN_PAGES`` pages are hidden (``decisions``); every other crop is asked of
   decider-vision for its category and band, then, with ``CAPTIONS_ENABLED``, described. A hidden crop is not
   described.

Every crop that passes the gates is returned and written, whatever its band: nothing is deleted. A region that fails
in pass 1 is logged and skipped; one that fails in pass 2 keeps its crop and goes out without a decision. Only a
document that cannot be opened, or an ``output_dir`` outside the storage, fails the job.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from evilflowers_worker.contract import Box, LayoutRegion, Region
from evilflowers_worker.judges import Judges, Panel
from PIL import Image

from evilflowers_image import crops, decisions, metrics
from evilflowers_image.decisions import FIGURE_KIND, REPEATED, Fingerprint
from evilflowers_image.settings import Settings, get_settings

logger = logging.getLogger(__name__)

KIND = "figure"


class Captioner(Protocol):
    model: str

    def describe(self, image: Image.Image, printed_caption: str | None) -> tuple[str | None, str | None]: ...


def gate(box: Box, size_px: tuple[int, int], settings: Settings) -> str | None:
    """Why a region is not kept as a figure, or None."""
    width, height = size_px
    if min(width, height) < settings.min_side_px:
        return "too small"
    if max(width, height) / max(min(width, height), 1) > settings.max_aspect_ratio:
        return "extreme aspect ratio"
    if crops.coverage(box) > settings.max_page_coverage:
        return "covers the page"
    return None


def _nothing() -> None:
    pass


@dataclass
class Crop:
    """A region that passed the gates: its crop is written; the decision is still to come."""

    region: Region
    fingerprint: Fingerprint


class FigureReader:
    def __init__(
        self, settings: Settings | None = None, captioner: Captioner | None = None, judges: Judges | None = None
    ):
        self.settings = settings or get_settings()
        self.captioner = captioner
        self.judges = judges

    def read(
        self,
        path: Path,
        output_dir: str,
        regions: Sequence[LayoutRegion],
        *,
        between: Callable[[], None] = _nothing,
    ) -> list[Region]:
        """The figures of one PDF. Raises when it cannot be opened or ``output_dir`` escapes the storage."""
        # A message is input: refuse a `..` or an absolute path before anything is opened or written.
        self.settings.storage_file(output_dir)
        with crops.PdfPages(path, self.settings.crop_dpi) as pages:
            return self.read_pages(pages, output_dir, regions, between=between)

    def read_pages(
        self,
        pages: crops.PageSource,
        output_dir: str,
        regions: Sequence[LayoutRegion],
        *,
        between: Callable[[], None] = _nothing,
    ) -> list[Region]:
        """The figures, crops written under ``output_dir``. Raises when ``output_dir`` escapes the storage.

        ``between`` runs before each region of each pass, outside the per-region error handling: the job's
        ``recheck``, whose ``Stop`` must end the work rather than skip one figure.
        """
        self.settings.storage_file(output_dir)
        cropped: list[Crop] = []
        for region in regions:
            between()
            try:
                crop = self.crop(pages, region, output_dir)
            except Exception:
                logger.exception("Figure on page %s skipped", region.page)
                metrics.record_region("error")
                continue
            if crop is not None:
                cropped.append(crop)

        hidden = decisions.repeated(
            [crop.fingerprint for crop in cropped],
            min_pages=self.settings.repeat_min_pages,
            max_distance=self.settings.repeat_max_distance,
        )
        panel = self.judges.panel() if self.judges is not None else None
        figures = []
        for index, crop in enumerate(cropped):
            between()
            if index in hidden:
                figures.append(crop.region.model_copy(update={"band": "hide", "decision": REPEATED}))
                metrics.record_region(REPEATED)
                continue
            try:
                figures.append(self.decide(crop.region, panel))
            except Exception:
                # The crop is written: it goes out without a decision rather than not at all.
                logger.exception("Decision failed for the figure on page %s", crop.region.page)
                figures.append(crop.region)
            metrics.record_region("kept")
        return figures

    def crop(self, pages: crops.PageSource, region: LayoutRegion, output_dir: str) -> Crop | None:
        page, dpi = pages.page(region.page)
        image = crops.render(page, crops.rect(region.bbox, page), dpi)
        if reason := gate(region.bbox, image.size, self.settings):
            logger.info("Figure on page %s dropped: %s", region.page, reason)
            metrics.record_region(reason)
            return None

        name = crops.crop_name(output_dir, region.page, "fig", region.seq)
        crops.save(image, self.settings.storage_file(name), self.settings.webp_quality)
        fingerprint = Fingerprint(page=region.page, hash=decisions.dhash(image), size=image.size)
        signals = {"dhash": f"{fingerprint.hash:016x}"} if fingerprint.hash is not None else None
        return Crop(
            region=Region(
                kind=KIND,
                page=region.page,
                seq=region.seq,
                bbox=region.bbox,
                image_path=name,
                caption=region.caption,
                printed_caption=region.caption,
                signals=signals,
            ),
            fingerprint=fingerprint,
        )

    def decide(self, region: Region, panel: Panel | None) -> Region:
        """The decider's category and band, then the optional description; reads the crop back only when asked."""
        if panel is None and self.captioner is None:
            return region
        assert region.image_path is not None
        with Image.open(self.settings.storage_file(region.image_path)) as stored:
            image = stored.convert("RGB")

        update: dict[str, Any] = {}
        provenance = dict(region.provenance)
        if panel is not None and self.judges is not None:
            verdict = panel.ask(
                self.judges.decider_vision,
                FIGURE_KIND,
                state=decisions.STATE,
                images=[crops.png(image, self.settings.judge_max_side)],
            )
            if verdict is not None:
                update |= verdict.region_fields() | {"category": verdict.verdict}
                provenance |= verdict.provenance()

        if self.captioner is not None and update.get("band") != "hide":
            try:
                description, category = self.captioner.describe(image, region.printed_caption)
                provenance["caption_model"] = self.captioner.model
                # The document's own caption and the model's description travel apart (IP-018 Phase 8); `caption`
                # is kept for catalogs that predate them. The decider's category, when there is one, wins.
                update |= {"description": description, "caption": region.printed_caption or description}
                update.setdefault("category", category)
            except Exception:
                # The crop and its position are still worth keeping without a description.
                logger.exception("Caption failed for the figure on page %s", region.page)

        return region.model_copy(update={**update, "provenance": provenance})
