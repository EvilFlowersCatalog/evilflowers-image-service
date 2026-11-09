"""The IP-018 figures job: read one PDF, post the figures to the catalog, report the job.

The analyzer dispatches the job and declares it at the run's `/start`; the run
finishes only when every declared job has reported `done` or `failed`. So the
job never ends silently: whatever goes wrong is reported to the catalog, unless
the catalog itself refused the run (409, `RunNotRunning`). The protocol is the
one of evilflowers-text-service's `ExtractionJob`.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from evilflowers_image.captions import OllamaCaptioner
from evilflowers_image.clients.catalog import CatalogClient, RunNotRunning
from evilflowers_image.figures import Captioner, FigureReader
from evilflowers_image.observability import bind, fail, metrics, span
from evilflowers_image.settings import Settings, get_settings

logger = logging.getLogger(__name__)

Outcome = Literal["done", "failed", "not_running"]


class FiguresJob:
    #: The job's name in the catalog (`/jobs/<name>`, `run.provenance[<name>]`).
    name = "figures"

    def __init__(
        self,
        run_id: str,
        source: str,
        output_dir: str,
        regions: Sequence[Mapping[str, Any]],
        *,
        settings: Settings | None = None,
        catalog: CatalogClient | None = None,
        captioner: Captioner | None = None,
    ):
        self.settings = settings or get_settings()
        self.run_id = run_id
        self.source = source
        self.output_dir = output_dir
        self.regions = regions
        self.catalog = catalog or CatalogClient(run_id, settings=self.settings)
        if captioner is None and self.settings.captions_enabled:
            captioner = OllamaCaptioner(self.settings)
        self.reader = FigureReader(self.settings, captioner)

    def extract(self) -> list[dict[str, Any]]:
        """Crop, gate and describe the regions. Raising (the PDF cannot be opened) fails the job."""
        with span("figures.extract", **{"figures.regions": len(self.regions)}) as current:
            kept = self.reader.read(self.settings.source_path(self.source), self.output_dir, self.regions)
            if current is not None:
                current.set_attribute("figures.kept", len(kept))
        return kept

    def provenance(self) -> dict[str, Any]:
        """What produced the results, stored as `run.provenance.figures`."""
        result: dict[str, Any] = {"image": self.settings.image_tag, "crop_dpi": self.settings.crop_dpi}
        if self.reader.captioner is not None:
            result["caption_model"] = self.reader.captioner.model
        return result

    def run(self) -> Outcome:
        with bind(run_id=self.run_id, job=self.name, source=self.source):
            try:
                kept = self.extract()
                self.catalog.regions(kept)
                self.catalog.job(self.name, status="done", provenance=self.provenance())
            except RunNotRunning:
                # The crops already written stay until the catalog deletes the run's folder.
                logger.warning("Run %s is not accepting results", self.run_id)
                return self._outcome("not_running")
            except Exception as error:
                logger.exception("Job %s failed for run %s", self.name, self.run_id)
                fail(error)
                self._report_failure(error)
                return self._outcome("failed")
            logger.info("Run %s: %d of %d figures kept", self.run_id, len(kept), len(self.regions))
            return self._outcome("done")

    def _report_failure(self, error: Exception) -> None:
        # Report it, or the run waits for this job forever.
        try:
            self.catalog.job(
                self.name, status="failed", error=f"{type(error).__name__}: {error}", provenance=self.provenance()
            )
        except RunNotRunning:
            logger.warning("Run %s is not accepting results", self.run_id)
        except Exception:
            logger.exception("Could not report the failed %s job for run %s", self.name, self.run_id)

    def _outcome(self, outcome: Outcome) -> Outcome:
        metrics.record_job(self.name, outcome)
        return outcome
