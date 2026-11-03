"""Figures of an extraction run (IP-018).

`evilflowers_image.figures` receives the figure regions the analyzer's layout
pass found, crops each one to WebP, drops what fails the gates, optionally
describes it with a multimodal model, and reports the regions and the job to
the catalog. A region that fails is logged and skipped; only a document that
cannot be opened fails the job.
"""

import logging
import os
from typing import List, Optional

import fitz
from celery import Celery

import captions
import crops
import settings
from catalog import Catalog, RunNotRunning

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("image")

JOB = "figures"

app = Celery("evilflowers_image", broker=settings.REDIS_URL)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="Europe/Bratislava",
    enable_utc=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


def gate(box: dict, size_px: tuple) -> Optional[str]:
    """Why a region is not kept as a figure, or None."""
    width, height = size_px
    if min(width, height) < settings.MIN_SIDE_PX:
        return "too small"
    if max(width, height) / max(min(width, height), 1) > settings.MAX_ASPECT_RATIO:
        return "extreme aspect ratio"
    if crops.coverage(box) > settings.MAX_PAGE_COVERAGE:
        return "covers the page"
    return None


def provenance() -> dict:
    result = {"image": settings.IMAGE_TAG, "crop_dpi": settings.CROP_DPI}
    if settings.CAPTIONS_ENABLED:
        result["caption_model"] = settings.CAPTION_MODEL
    return result


@app.task(name="evilflowers_image.figures", queue=settings.QUEUE)
def figures(run_id: str, source: str, output_dir: str, regions: List[dict], **_):
    catalog = Catalog(run_id)
    try:
        document = fitz.open(os.path.join(settings.STORAGE_PATH, source))
    except Exception as error:
        logger.exception("Cannot open %s", source)
        catalog.job(JOB, failed=True, error=f"Cannot open the PDF: {error}")
        return

    kept = []
    with document:
        for region in regions:
            try:
                result = _figure(document, region, output_dir)
            except Exception:
                logger.exception("Run %s: figure on page %s skipped", run_id, region.get("page"))
                continue
            if result:
                kept.append(result)

    try:
        catalog.regions(kept)
        catalog.job(JOB, provenance=provenance())
    except RunNotRunning:
        logger.warning("Run %s is not accepting results; %d figures dropped", run_id, len(kept))
        return
    logger.info("Run %s: %d of %d figures kept", run_id, len(kept), len(regions))


def _figure(document: fitz.Document, region: dict, output_dir: str) -> Optional[dict]:
    page = document[region["page"] - 1]
    image = crops.render(page, crops.rect(region["bbox"], page), settings.CROP_DPI)
    reason = gate(region["bbox"], image.size)
    if reason:
        logger.info("Figure on page %s dropped: %s", region["page"], reason)
        return None

    name = crops.crop_name(output_dir, region["page"], "fig", region["seq"])
    crops.save(image, name)

    caption, category = region.get("caption"), None
    region_provenance = {}
    if settings.CAPTIONS_ENABLED:
        try:
            described, category = captions.describe(image, region.get("caption"))
            caption = described or caption
            region_provenance = {"caption_model": settings.CAPTION_MODEL, "printed_caption": region.get("caption")}
        except Exception:
            # The crop and its position are still worth keeping without a description.
            logger.exception("Caption failed for page %s", region["page"])

    return {
        "kind": "figure",
        "page": region["page"],
        "seq": region["seq"],
        "bbox": region["bbox"],
        "image_path": name,
        "caption": caption,
        "category": category,
        "provenance": region_provenance,
    }
