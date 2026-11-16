"""The IP-018 figures job: crop, gate and describe the regions of one PDF, post them, report the job.

The lifecycle is evilflowers-worker's ``LeafJob.run``: the delivery cap, the run check (``already_done`` /
``not_running`` / ``superseded`` stop before the work), ``extract``, ``publish`` with ``?attempt=``, and the terminal
report under the message's ``job`` (a batch, ``figures:0001-0008``) or ``figures``.
"""

from typing import Any

from evilflowers_worker.contract import Region, RegionsJob
from evilflowers_worker.jobs import LeafJob
from evilflowers_worker.judges import Judges
from evilflowers_worker.observability import span

from evilflowers_image.captions import OllamaCaptioner
from evilflowers_image.decisions import judges_for
from evilflowers_image.figures import Captioner, FigureReader
from evilflowers_image.settings import Settings


def captioner_for(settings: Settings) -> Captioner | None:
    return OllamaCaptioner(settings) if settings.captions_enabled else None


class FiguresJob(LeafJob[RegionsJob, list[Region]]):
    kind = "figures"
    settings: Settings

    def __init__(
        self,
        message: RegionsJob,
        *,
        settings: Settings,
        captioner: Captioner | None = None,
        judges: Judges | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, settings=settings, **kwargs)
        self.reader = FigureReader(
            settings, captioner or captioner_for(settings), judges if judges is not None else judges_for(settings)
        )

    def extract(self) -> list[Region]:
        """Crop, gate, decide and describe the regions. Raising (the PDF cannot be opened) fails the job."""
        regions = self.message.regions
        if not regions:
            # An empty batch still reports, so the run can finish; there is nothing to open.
            return []
        with span("figures.extract", **{"evilflowers.figures.regions": len(regions)}) as current:
            kept = self.reader.read(
                self.settings.source_path(self.message.source),
                self.message.output_dir,
                regions,
                between=self.recheck,
            )
            if current is not None:
                current.set_attribute("evilflowers.figures.kept", len(kept))
        return kept

    def publish(self, result: list[Region]) -> None:
        self.catalog.regions(result)

    def provenance(self) -> dict[str, Any]:
        """What produced the results, stored as `run.provenance.figures`."""
        result = {**super().provenance(), "crop_dpi": self.settings.crop_dpi}
        if self.reader.captioner is not None:
            result["caption_model"] = self.reader.captioner.model
        return result
