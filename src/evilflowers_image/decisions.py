"""Is a crop a real figure or page furniture? The decision path both figures tasks share (#6, #7).

1. **Repeated image, no model.** A perceptual hash (dHash, 64 bits) per crop. The same image on at least
   ``REPEAT_MIN_PAGES`` distinct pages of one job is a stamp, logo or ornament: ``decision: repeated``, ``band: hide``,
   no ``p``. A job sees only its own regions (a catalog batch, ``figures:0001-0008``, sees 8 pages), so a repeat that
   spans batches goes to the decider instead. A near-uniform crop gets no hash (every blank or flat box would match).
2. **decider-vision.** Every other crop is asked ``FIGURE_KIND`` through the kit's judges
   (``evilflowers_worker.judges``): the answer is the region's ``category``, and with ``JUDGE_THRESHOLDS`` measured
   (knowledge#65) its ``band``. A judge that does not answer leaves the region as it was: posted without a band.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from evilflowers_worker.judges import Choice, Judges, JudgeSettings
from PIL import Image, ImageStat

from evilflowers_image.settings import get_settings

#: The question asked of decider-vision; ``figure_kind`` is the key of its thresholds and of its metrics.
FIGURE_KIND = Choice(
    id="figure_kind",
    instructions="What is this image?",
    criteria={
        "chart": "chart",
        "diagram": "diagram",
        "photo": "photo",
        "map": "map",
        "table": "table drawn as an image",
        "formula": "formula",
        "stamp": "stamp, signature or logo",
        "decoration": "decoration",
        "scan": "scanned full page",
        "blank": "blank",
    },
    reject={"stamp", "decoration", "scan", "blank"},
)
STATE = "A region cropped from a page of a publication."

#: ``decision`` of a crop hidden as page furniture.
REPEATED = "repeated"
#: Below this grey-level standard deviation a crop is near-uniform and gets no hash.
_FLAT = 4.0
#: Two crops of the same image have aspect ratios within this factor of each other.
_ASPECT_TOLERANCE = 1.1


def dhash(image: Image.Image) -> int | None:
    """The 64-bit difference hash of ``image``, or ``None`` for a near-uniform one."""
    grey = image.convert("L")
    if ImageStat.Stat(grey).stddev[0] < _FLAT:
        return None
    pixels = grey.resize((9, 8), Image.Resampling.LANCZOS).tobytes()  # one byte per pixel, row by row
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | (pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return bits


@dataclass(frozen=True)
class Fingerprint:
    page: int
    hash: int | None
    size: tuple[int, int]

    def same_image(self, other: "Fingerprint", max_distance: int) -> bool:
        if self.hash is None or other.hash is None:
            return False
        if (self.hash ^ other.hash).bit_count() > max_distance:
            return False
        mine, theirs = self.size[0] / self.size[1], other.size[0] / other.size[1]
        return max(mine, theirs) / min(mine, theirs) <= _ASPECT_TOLERANCE


def repeated(fingerprints: Sequence[Fingerprint], *, min_pages: int, max_distance: int) -> set[int]:
    """Indexes of the crops whose image appears on at least ``min_pages`` distinct pages (their own included)."""
    found = set()
    for index, mine in enumerate(fingerprints):
        pages = {other.page for other in fingerprints if mine.same_image(other, max_distance)}
        if len(pages) >= min_pages:
            found.add(index)
    return found


_process_judges: Judges | None = None


def judges_for(settings: JudgeSettings) -> Judges:
    """The process's judges for its own settings (their circuit breakers live as long as the process); fresh ones for
    any other settings object (tests)."""
    global _process_judges
    if settings is not get_settings():
        return Judges.from_settings(settings)
    if _process_judges is None:
        _process_judges = Judges.from_settings(settings)
    return _process_judges
