"""``evilflowers_image.standalone.figures``: the figures of cleaned leaves for the books digitalizer, no catalog (#7).

The message is the kit's ``StandaloneJob`` (evilflowers-worker#5) plus, in the analyzer's standalone shapes
(evilflowers-analyzer-service#8):

- ``leaves``: ``[{leaf, image}]``, the leaf number and its image relative to ``STORAGE_PATH``. Absent: ``inputs`` in
  order are leaves 1, 2, … . When the message has ``leaves`` but no ``inputs``, ``inputs`` are their images.
- ``regions``: rows of the analyzer's ``regions.json``, ``{leaf, kind, seq, bbox: [x0, y0, x1, y1], caption}``
  (fractions, top-left origin). Rows whose ``kind`` is not a picture (``picture``, ``figure``, ``chart``) are ignored,
  so the orchestrator can pass the analyzer's output as it is.

The job runs the catalog task's code (``FigureReader``: crops, gates, the repeated-image check and decider-vision) on
the leaves, writes the WebP crops and ``figures.json`` into its ``output_dir``, then the outcome file last, and
returns ``{job, figures}`` for the orchestrator's ``link``. ``figures.json`` rows are the catalog's region fields with
``leaf`` for ``page``, ``bbox`` as ``[x0, y0, x1, y1]`` and ``crop`` (the file name in ``output_dir``) for
``image_path``; ``band: review`` is what the page studio shows as a disputed region.

A failure writes a ``failed`` outcome with the error and raises, so ``link_error`` fires; past the delivery cap too.
A deliberate requeue (SIGTERM) never writes one: the redelivery keeps the token.
"""

import json
import logging
from pathlib import Path
from typing import Any, Literal, NoReturn

from evilflowers_worker.contract import Box, LayoutRegion, Region, StandaloneJob, dump
from evilflowers_worker.judges import Judges
from evilflowers_worker.observability import bind, metrics
from evilflowers_worker.outcome import OutcomeFile, atomic_write, write_outcome
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from evilflowers_image import crops
from evilflowers_image.decisions import judges_for
from evilflowers_image.figures import Captioner, FigureReader
from evilflowers_image.jobs import captioner_for
from evilflowers_image.settings import Settings, get_settings

logger = logging.getLogger(__name__)

TASK = "evilflowers_image.standalone.figures"
#: The analyzer's Docling labels of a picture.
PICTURE_KINDS = frozenset({"picture", "figure", "chart"})
FIGURES_FILE = "figures.json"
#: ``image_job_outcome_total{job}``.
KIND = "standalone_figures"


class Leaf(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    leaf: int = Field(ge=1)
    #: Relative to ``STORAGE_PATH``.
    image: str = Field(min_length=1)


class LeafRegion(BaseModel):
    """A row of the analyzer's ``regions.json``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    leaf: int = Field(ge=1)
    seq: int = Field(ge=0)
    bbox: Box
    kind: str | None = None
    caption: str | None = None

    @field_validator("bbox", mode="before")
    @classmethod
    def _bbox_list(cls, value: Any) -> Any:
        """``[x0, y0, x1, y1]`` as the analyzer writes it, or the catalog's ``{x0, y0, x1, y1}``."""
        if isinstance(value, list | tuple) and len(value) == 4:
            return dict(zip(("x0", "y0", "x1", "y1"), value, strict=True))
        return value

    @property
    def picture(self) -> bool:
        return self.kind is None or self.kind in PICTURE_KINDS

    def layout(self) -> LayoutRegion:
        return LayoutRegion(page=self.leaf, seq=self.seq, bbox=self.bbox, caption=self.caption)


class StandaloneFiguresJob(StandaloneJob):
    leaves: list[Leaf] = Field(default_factory=list)
    regions: list[LeafRegion] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _inputs_from_leaves(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("inputs") and isinstance(data.get("leaves"), list):
            images = [leaf.get("image") for leaf in data["leaves"] if isinstance(leaf, dict)]
            return {**data, "inputs": images}
        return data

    @model_validator(mode="after")
    def _distinct_leaves(self) -> "StandaloneFiguresJob":
        numbers = [leaf.leaf for leaf in self.all_leaves()]
        if len(numbers) != len(set(numbers)):
            raise ValueError("leaf numbers repeat")
        return self

    def all_leaves(self) -> list[Leaf]:
        """``leaves``, or ``inputs`` numbered from 1."""
        return self.leaves or [Leaf(leaf=number, image=image) for number, image in enumerate(self.inputs, 1)]

    def leaf_paths(self, settings: Settings) -> dict[int, Path]:
        """Every leaf's image as an absolute path, checked to stay under ``STORAGE_PATH`` (a message is input)."""
        return {leaf.leaf: settings.storage_file(leaf.image) for leaf in self.all_leaves()}


class FiguresOutcome(OutcomeFile):
    status: Literal["done", "failed"]
    job: str
    error: str | None = None
    #: ``figures.json``, relative to ``STORAGE_PATH``.
    figures: str | None = None
    #: Every leaf looked at, those without a figure included.
    leaves: list[int] = Field(default_factory=list)


def row(figure: Region, output_dir: str) -> dict[str, Any]:
    """A ``figures.json`` row: the region's fields with ``leaf``, a list ``bbox`` and ``crop`` in ``output_dir``."""
    fields = dump(figure)
    fields["leaf"] = fields.pop("page")
    box = figure.bbox
    fields["bbox"] = [box.x0, box.y0, box.x1, box.y1]
    image_path = fields.pop("image_path", None)
    if image_path is not None:
        fields["crop"] = image_path.removeprefix(f"{output_dir.rstrip('/')}/")
    return fields


class StandaloneFigures:
    """The task's handler and its ``on_capped`` / ``on_invalid``; one per process (its judges hold the breakers)."""

    def __init__(
        self, settings: Settings | None = None, *, captioner: Captioner | None = None, judges: Judges | None = None
    ):
        self.settings = settings or get_settings()
        self.reader = FigureReader(
            self.settings,
            captioner or captioner_for(self.settings),
            judges if judges is not None else judges_for(self.settings),
        )

    def run(self, message: StandaloneFiguresJob, delivery: int) -> dict[str, Any]:
        with bind(run_id=message.run_id, job_id=message.job):
            try:
                figures = self.extract(message)
            except Exception as error:
                logger.exception("Standalone figures job %s failed", message.job)
                self.fail(message, f"{type(error).__name__}: {error}")
            metrics.record_job(KIND, "done")
            return {"job": message.job, "figures": figures}

    def extract(self, message: StandaloneFiguresJob) -> int:
        """Crops and ``figures.json``, then the ``done`` outcome; the number of figures."""
        settings = self.settings
        message.prepare_output(settings)
        leaves = message.leaf_paths(settings)
        regions = [region.layout() for region in message.regions if region.picture]
        # The orchestrator applies `leaves` as given: a leaf it named must not be dropped silently.
        for region in regions:
            if region.page not in leaves:
                raise ValueError(f"region {region.seq} names leaf {region.page}, which the message does not list")
        for number, path in leaves.items():
            if not path.is_file():
                raise FileNotFoundError(f"leaf {number}: no image at {path.relative_to(settings.storage_path)}")
        with crops.LeafPages(leaves, settings.crop_dpi) as pages:
            figures = self.reader.read_pages(pages, message.output_dir, regions)
        rows = [row(figure, message.output_dir) for figure in figures]
        atomic_write(
            message.output_file(settings, FIGURES_FILE), json.dumps(rows, ensure_ascii=False).encode()
        )  # the output first …
        done = FiguresOutcome(
            run_id=message.run_id,
            token=message.token,
            status="done",
            job=message.job,
            figures=f"{message.output_dir.rstrip('/')}/{FIGURES_FILE}",
            leaves=sorted(leaves),
        )
        write_outcome(settings, message.outcome, done)  # … then the outcome, the commit marker
        return len(rows)

    def give_up(self, message: StandaloneFiguresJob, delivery: int) -> NoReturn:
        """Past the delivery cap: the job killed its worker every time."""
        self.fail(message, f"gave up after {delivery - 1} deliveries: the worker died during each of them")

    def invalid(self, kwargs: dict[str, Any], error: ValidationError) -> NoReturn:
        """A message that does not validate: a ``failed`` outcome when it names one, then raise (``link_error``)."""
        names = {key: kwargs.get(key) for key in ("run_id", "token", "outcome", "job")}
        if all(isinstance(value, str) and value for value in names.values()):
            failed = FiguresOutcome(
                run_id=names["run_id"], token=names["token"], status="failed", job=names["job"], error=str(error)
            )
            try:
                write_outcome(self.settings, names["outcome"], failed)
            except ValueError:
                logger.error("The invalid message's outcome path escapes STORAGE_PATH: %r", names["outcome"])
        metrics.record_job(KIND, "failed")
        raise error

    def fail(self, message: StandaloneFiguresJob, error: str) -> NoReturn:
        """The ``failed`` outcome, then raise: the task fails and the orchestrator's ``link_error`` fires."""
        failed = FiguresOutcome(
            run_id=message.run_id, token=message.token, status="failed", job=message.job, error=error
        )
        write_outcome(self.settings, message.outcome, failed)
        metrics.record_job(KIND, "failed")
        raise RuntimeError(error)
