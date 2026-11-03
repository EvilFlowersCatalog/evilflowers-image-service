import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


#: Celery broker: the catalog's Redis.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/7")
QUEUE = os.getenv("IMAGE_QUEUE", "evilflowers_image")

#: The catalog's storage root (originals are read, crops written).
STORAGE_PATH = os.getenv("STORAGE_PATH", "/mnt/data")

CATALOG_API_URL = os.getenv("CATALOG_API_URL", "http://catalog:8000")
#: API key (bearer JWT) of the catalog user holding `extraction.ingest_extraction`.
CATALOG_API_KEY = os.getenv("CATALOG_API_KEY")
IMAGE_TAG = os.getenv("IMAGE_TAG", "dev")

#: Crop resolution and quality.
CROP_DPI = int(os.getenv("CROP_DPI", "144"))
WEBP_QUALITY = int(os.getenv("WEBP_QUALITY", "82"))

#: Gates (IP-018 Phase 2): smaller than this on either side at CROP_DPI, longer
#: than this ratio, or covering more of the page than this is not a figure.
MIN_SIDE_PX = int(os.getenv("MIN_SIDE_PX", "80"))
MAX_ASPECT_RATIO = float(os.getenv("MAX_ASPECT_RATIO", "8"))
MAX_PAGE_COVERAGE = float(os.getenv("MAX_PAGE_COVERAGE", "0.9"))

#: Captions and categories by a multimodal model behind an Ollama endpoint
#: (Q8: the only practical route on a CPU host). Off without a GPU or endpoint;
#: the caption found next to the figure in the document is kept either way.
CAPTIONS_ENABLED = _flag("CAPTIONS_ENABLED", "0")
#: Full chat URL, e.g. http://ollama:11434/api/chat or https://ollama.com/api/chat.
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434/api/chat")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
CAPTION_MODEL = os.getenv("CAPTION_MODEL", "qwen2.5vl:7b")
CAPTION_TIMEOUT = int(os.getenv("CAPTION_TIMEOUT", "180"))
#: Longest side sent to the model.
CAPTION_MAX_SIDE = int(os.getenv("CAPTION_MAX_SIDE", "1024"))
