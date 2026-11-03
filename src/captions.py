"""Figure captions and categories from a multimodal model (IP-018 Q8).

The model sees the crop and the caption printed next to it in the document,
and answers JSON: a one- or two-sentence description and one category.
"""

import base64
import io
import json
import logging
from typing import Optional, Tuple

import requests
from PIL import Image

import settings

logger = logging.getLogger(__name__)

CATEGORIES = ("chart", "diagram", "photo", "map", "drawing", "screenshot", "other")

PROMPT = (
    "You see one figure cropped from a page of a publication.{caption}\n"
    "Describe what the figure shows in one or two plain sentences, in the language of the printed "
    "caption if there is one, else in English. Then pick its category from: "
    + ", ".join(CATEGORIES)
    + '.\nAnswer only JSON: {{"caption": "...", "category": "..."}}'
)


def _encode(image: Image.Image) -> str:
    image = image.copy()
    image.thumbnail((settings.CAPTION_MAX_SIDE, settings.CAPTION_MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def parse(content: str) -> Tuple[Optional[str], Optional[str]]:
    """`(caption, category)` from the model's answer; a category outside the list becomes `other`."""
    try:
        answer = json.loads(content[content.find("{") : content.rfind("}") + 1])
    except (ValueError, TypeError):
        return None, None
    caption = str(answer.get("caption") or "").strip() or None
    category = str(answer.get("category") or "").strip().lower() or None
    if category and category not in CATEGORIES:
        category = "other"
    return caption, category


def describe(image: Image.Image, printed_caption: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    caption = f'\nIts printed caption is: "{printed_caption}"' if printed_caption else ""
    headers = {"Authorization": f"Bearer {settings.OLLAMA_API_KEY}"} if settings.OLLAMA_API_KEY else {}
    response = requests.post(
        settings.OLLAMA_ENDPOINT,
        json={
            "model": settings.CAPTION_MODEL,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": PROMPT.format(caption=caption), "images": [_encode(image)]}],
        },
        headers=headers,
        timeout=settings.CAPTION_TIMEOUT,
    )
    response.raise_for_status()
    return parse(response.json().get("message", {}).get("content", ""))
