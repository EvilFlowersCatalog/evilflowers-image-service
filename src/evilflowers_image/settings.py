"""Configuration of the worker: the kit's ``WorkerSettings`` and ``JudgeSettings`` plus the figures' own fields.

The broker, delivery semantics (``WORKER_SOFT_SHUTDOWN_TIMEOUT``, ``WORKER_CANCEL_TIMEOUT``, ``MAX_DELIVERIES``,
``BROKER_VISIBILITY_TIMEOUT``), storage, logs and the catalog ingestion API come from evilflowers-worker. So do the
judges (``DECIDER_ENABLED``, ``DECIDER_VISION_URL``, ``DECIDER_TIMEOUT``, ``JUDGE_THRESHOLDS``, the per-job budget;
the ``judges`` extra). Every field keeps the environment variable name the deployments already set (``IMAGE_QUEUE``,
``CAPTIONS_ENABLED`` …).
"""

from functools import lru_cache

from evilflowers_worker.judges import JudgeSettings
from evilflowers_worker.settings import WorkerSettings
from pydantic import AliasChoices, Field, SecretStr


class Settings(WorkerSettings, JudgeSettings):
    #: The catalog figures job. ``QUEUE`` is what the kit's test harness sets.
    queue: str = Field("evilflowers_image", validation_alias=AliasChoices("IMAGE_QUEUE", "QUEUE"))

    # -- Standalone (books digitalizer, #7) --------------------------------------------------------------------------
    #: On: the worker consumes the two standalone queues instead of ``IMAGE_QUEUE`` and needs no catalog key. The
    #: Deployment points ``REDIS_URL`` at the digitalizer's db (8 on dev); an interactive-only replica narrows the
    #: queues with ``-Q evilflowers_image.standalone.interactive``.
    standalone: bool = Field(False, validation_alias=AliasChoices("IMAGE_STANDALONE", "STANDALONE"))
    standalone_queue: str = "evilflowers_image.standalone"
    interactive_queue: str = "evilflowers_image.standalone.interactive"

    # -- Crops ------------------------------------------------------------------------------
    crop_dpi: int = 144
    webp_quality: int = 82

    # -- Gates (IP-018 Phase 2) ------------------------------------------------------------
    #: Smaller than this on either side at `crop_dpi`, longer than this ratio, or covering
    #: more of the page than this is not a figure.
    min_side_px: int = 80
    max_aspect_ratio: float = 8.0
    max_page_coverage: float = 0.9

    # -- Keep/hide (#6) --------------------------------------------------------------------------------------------
    #: The same image (perceptual hash) on at least this many distinct pages of one job is page furniture: hidden
    #: without asking a model. The catalog never re-bands it, so keep this conservative.
    repeat_min_pages: int = Field(3, ge=2)
    #: Bits (of 64) two hashes may differ in and still be the same image.
    repeat_max_distance: int = Field(4, ge=0, le=16)
    #: Longest side of the crop sent to decider-vision, in pixels (the service scales to 448 itself).
    judge_max_side: int = Field(448, ge=32)

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

    def queues(self) -> list[str]:
        """What this worker consumes: the catalog queue, or both standalone queues (interactive first)."""
        return [self.interactive_queue, self.standalone_queue] if self.standalone else [self.queue]


@lru_cache
def get_settings() -> Settings:
    return Settings()
