"""Configuration of the worker: the kit's ``WorkerSettings`` plus the figures' own fields.

The broker, delivery semantics (``WORKER_SOFT_SHUTDOWN_TIMEOUT``, ``WORKER_CANCEL_TIMEOUT``, ``MAX_DELIVERIES``,
``BROKER_VISIBILITY_TIMEOUT``), storage, logs and the catalog ingestion API come from evilflowers-worker. Every field
keeps the environment variable name the deployments already set (``IMAGE_QUEUE``, ``CAPTIONS_ENABLED`` …).
"""

from functools import lru_cache

from evilflowers_worker.settings import WorkerSettings
from pydantic import AliasChoices, Field, SecretStr


class Settings(WorkerSettings):
    #: The figures job. ``QUEUE`` is what the kit's test harness sets.
    queue: str = Field("evilflowers_image", validation_alias=AliasChoices("IMAGE_QUEUE", "QUEUE"))

    # -- Crops ------------------------------------------------------------------------------
    crop_dpi: int = 144
    webp_quality: int = 82

    # -- Gates (IP-018 Phase 2) ------------------------------------------------------------
    #: Smaller than this on either side at `crop_dpi`, longer than this ratio, or covering
    #: more of the page than this is not a figure.
    min_side_px: int = 80
    max_aspect_ratio: float = 8.0
    max_page_coverage: float = 0.9

    # -- Captions: a multimodal model behind an Ollama endpoint (IP-018 Q8) -----------------
    #: Off without a GPU or an endpoint; the caption printed next to the figure is kept either way.
    captions_enabled: bool = False
    #: Full chat URL, e.g. http://ollama:11434/api/chat or https://ollama.com/api/chat.
    ollama_endpoint: str = "http://ollama:11434/api/chat"
    ollama_api_key: SecretStr | None = None
    caption_model: str = "qwen2.5vl:7b"
    #: Seconds per figure.
    caption_timeout: float = 180.0
    #: Longest side of the image sent to the model, in pixels.
    caption_max_side: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
