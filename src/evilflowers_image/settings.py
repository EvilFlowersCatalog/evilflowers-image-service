"""Configuration of the worker: one typed object read from the environment (and `.env`).

Every field keeps the environment variable name the deployments already set
(``REDIS_URL``, ``IMAGE_QUEUE``, ``CATALOG_API_KEY``, ``CAPTIONS_ENABLED`` …),
so the move from the old flat ``settings.py`` needs no change in the k8s manifests.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True, populate_by_name=True)

    # -- Celery -------------------------------------------------------------------
    #: The broker: the catalog's Redis.
    redis_url: str = "redis://redis:6379/7"
    #: The figures job.
    queue: str = Field("evilflowers_image", validation_alias=AliasChoices("IMAGE_QUEUE", "QUEUE"))
    #: Seconds before Redis redelivers an unacknowledged message. The job acknowledges
    #: late, so this must outlast the longest book (captions make it slow).
    broker_visibility_timeout: int = 7200

    # -- Storage and provenance -----------------------------------------------------
    #: The catalog's storage root: originals are read here, crops written.
    storage_path: Path = Path("/mnt/data")
    #: Built into the image by CI; recorded in every run's provenance and as `service.version`.
    image_tag: str = "dev"

    # -- Catalog ingestion API (IP-018) ---------------------------------------------
    catalog_api_url: str = "http://catalog:8000"
    #: API key (bearer JWT) of the catalog user holding `extraction.ingest_extraction`.
    catalog_api_key: SecretStr | None = None
    #: Rows per request; keeps each body well under Django's 2.5 MB upload limit.
    catalog_batch_size: int = 100
    catalog_attempts: int = 4
    catalog_timeout: float = 120.0

    # -- Logs ---------------------------------------------------------------------------
    #: `json` (one object per line, what Loki parses) or `text` (Celery's own format, for a terminal).
    log_format: Literal["json", "text"] = "json"

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

    def source_path(self, source: str) -> Path:
        """Absolute path of a file the catalog names relative to its storage root."""
        return self.storage_path / source


@lru_cache
def get_settings() -> Settings:
    return Settings()
