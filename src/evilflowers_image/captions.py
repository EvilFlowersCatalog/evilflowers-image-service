"""Figure descriptions and categories from a multimodal model behind an Ollama endpoint (IP-018 Q8).

The model sees the crop and the caption printed next to it in the document,
and answers JSON: a one- or two-sentence description and one category.
"""

import base64
import io
import json
import time

import requests
from PIL import Image

from evilflowers_image.clients.http import session
from evilflowers_image.observability import metrics, span
from evilflowers_image.settings import Settings, get_settings

CATEGORIES = ("chart", "diagram", "photo", "map", "drawing", "screenshot", "other")

PROMPT = (
    "You see one figure cropped from a page of a publication.{caption}\n"
    "Describe what the figure shows in one or two plain sentences, in the language of the printed "
    "caption if there is one, else in English. Then pick its category from: "
    + ", ".join(CATEGORIES)
    + '.\nAnswer only JSON: {{"caption": "...", "category": "..."}}'
)


def parse(content: str) -> tuple[str | None, str | None]:
    """`(description, category)` from the model's answer; a category outside the list becomes `other`."""
    try:
        answer = json.loads(content[content.find("{") : content.rfind("}") + 1])
    except (ValueError, TypeError):
        return None, None
    if not isinstance(answer, dict):
        return None, None
    description = str(answer.get("caption") or "").strip() or None
    category = str(answer.get("category") or "").strip().lower() or None
    if category and category not in CATEGORIES:
        category = "other"
    return description, category


class OllamaCaptioner:
    """Describes one figure per request (``POST /api/chat``, ``format: json``, no streaming)."""

    def __init__(self, settings: Settings | None = None, http: requests.Session | None = None):
        self.settings = settings or get_settings()
        self.http = http or session(self.settings.ollama_api_key)

    @property
    def model(self) -> str:
        return self.settings.caption_model

    def _encode(self, image: Image.Image) -> str:
        image = image.copy()
        image.thumbnail((self.settings.caption_max_side, self.settings.caption_max_side))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def describe(self, image: Image.Image, printed_caption: str | None) -> tuple[str | None, str | None]:
        caption = f'\nIts printed caption is: "{printed_caption}"' if printed_caption else ""
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": PROMPT.format(caption=caption), "images": [self._encode(image)]}],
        }
        started, outcome = time.perf_counter(), "error"
        try:
            with span("figures.caption", **{"gen_ai.request.model": self.model}):
                response = self.http.post(
                    self.settings.ollama_endpoint, json=payload, timeout=self.settings.caption_timeout
                )
                response.raise_for_status()
                result = parse(response.json().get("message", {}).get("content", ""))
            outcome = "described" if result[0] else "unparsed"
            return result
        finally:
            metrics.record_caption(self.model, outcome, time.perf_counter() - started)
