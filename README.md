# EvilFlowers Image Service

The Celery worker that handles the figures of an IP-018 extraction run (Intelligent Viewer, catalog
`docs/proposals/posts/ip-018-intelligent-viewer.md`), and the same figures for the books digitalizer. For each figure
region that `evilflowers-analyzer-service`'s layout pass found, it writes a WebP crop and drops slivers and full-page
scans. It then decides whether the crop is a real figure or page furniture (`keep` / `review` / `hide`, #6), and
optionally asks a multimodal model for a description. The result goes to
[EvilFlowersCatalog](https://github.com/EvilFlowersCatalog/EvilFlowersCatalog), or into an outcome file for the
digitalizer. No model runs in this process.

![Figure keep/hide in both figures tasks](docs/diagrams/sequence-figure-decision.svg)

## Tasks

The task names, queues and argument shapes are a contract with their callers (`tests/test_worker.py` guards it).

| Task | Queue | Sent by | Does |
|---|---|---|---|
| `evilflowers_image.figures` | `evilflowers_image` (`IMAGE_QUEUE`) | analyzer, kwargs `run_id, source, output_dir, regions[, job, attempt]` (`RegionsJob`) | Crops, gates, decides and optionally describes each figure region. Posts them to `/regions`, then reports `/jobs/<job>`. |
| `evilflowers_image.standalone.figures` | `evilflowers_image.standalone`, `evilflowers_image.standalone.interactive` (`IMAGE_STANDALONE=1`) | books digitalizer, `StandaloneFiguresJob` + `link` / `link_error` | The same on cleaned leaf images. Writes the crops and `figures.json` into `output_dir`, then the outcome file. No catalog. |

`regions` is `[{page, seq, bbox: {x0, y0, x1, y1}, caption}]`: page fractions with a top-left origin on the 1-based
page. `caption` is the caption printed in the document, if the analyzer found one. `job` is the catalog job to report
under: a layout batch such as `figures:0001-0008`, or `figures` when absent. `attempt` comes from the catalog's
`/start`; it goes back as `?attempt=` on every write. Unknown kwargs are ignored. For each region the job:

1. renders the box at `CROP_DPI` (144);
2. drops it if its shorter side is under `MIN_SIDE_PX` (80), its aspect ratio is over `MAX_ASPECT_RATIO` (8), or it
   covers more than `MAX_PAGE_COVERAGE` (0.9) of the page;
3. writes `<STORAGE_PATH>/<output_dir>/p012-fig03.webp` (`WEBP_QUALITY` 82) and hashes it (dHash, 64 bits, in
   `signals.dhash`);
4. **repeated image, no model:** the same hash (`REPEAT_MAX_DISTANCE` bits, 4) on at least `REPEAT_MIN_PAGES` (3)
   distinct pages of the job is page furniture: `decision: repeated`, `band: hide`, no `p`. A job sees only its own
   regions (a batch, `figures:0001-0008`, sees 8 pages), so a repeat that spans batches goes to the decider instead.
   A near-uniform crop gets no hash;
5. **decider-vision** (`DECIDER_ENABLED`, `DECIDER_VISION_URL`; evilflowers-worker's `judges` extra) is asked the
   `figure_kind` question for every other crop. The answers are `chart`, `diagram`, `photo`, `map`, `table`,
   `formula`, `stamp`, `decoration`, `scan` and `blank`, and the last four reject the figure. The answer becomes
   `decision` and `category`, with `p` and `decider_model` (`model@revision`). The band follows `JUDGE_THRESHOLDS`
   (knowledge#65): a rejecting answer with `p >= hide` → `hide`, a keeping one with `p >= keep` → `keep`, anything
   else → `review`. With no thresholds the region has no `band`, and the catalog bands `p` + `decision` itself. A
   judge that is off, unreachable, refusing, over the job's budget (`JUDGE_BUDGET_CALLS`, `JUDGE_BUDGET_SECONDS`) or
   behind an open circuit breaker leaves the region unbanded, as before. It never fails the job;
6. with `CAPTIONS_ENABLED`, and unless the band is `hide`, sends a thumbnail and the printed caption to an Ollama
   endpoint (`OLLAMA_ENDPOINT`, `/api/chat`, `format: json`, model `CAPTION_MODEL`). The answer is `description` and
   one `category`, which is used only when the decider gave none. A failing caption keeps the crop.

Every crop that passes the gates is written and posted, whatever its band: nothing is deleted. Each region is posted
with `kind: figure`, `image_path`, `bbox`, `printed_caption`, `description`, `category`, `caption`
(`printed_caption or description`, kept for catalogs that predate the split) and, when decided, `band`, `p`,
`decision`, `decider_model` and `signals` (EvilFlowersCatalog#189).

### Standalone figures (books digitalizer)

`evilflowers_image.standalone.figures` runs the same code on cleaned leaf images, with no catalog (#7; the
digitalizer's `docs/design/target-architecture.md` §3, §6). The message is the kit's `StandaloneJob` (`run_id`, `job`,
`token`, `inputs`, `output_dir`, `outcome`), in the analyzer's standalone shapes (evilflowers-analyzer-service#8):

- `leaves`: `[{leaf, image}]`, paths relative to `STORAGE_PATH`. Without `leaves`, `inputs` in order are leaves
  1, 2, …; without `inputs`, the leaves' images are used as `inputs`.
- `regions`: the rows of the analyzer's `regions.json`, `{leaf, kind, seq, bbox: [x0, y0, x1, y1], caption}`. Rows
  whose `kind` is not `picture`, `figure` or `chart` are ignored, so the analyzer's output can be passed as it is.

A leaf is opened by PyMuPDF as a one-page document sized by its DPI metadata. It is rendered at `CROP_DPI`, capped
at the image's own resolution so a crop is never upsampled. The job writes `p003-fig01.webp` crops and `figures.json`
into `output_dir`, then the outcome file last (atomic). It returns `{job, figures}` for the orchestrator's `link`:

```json
{"run_id": "42", "token": "…", "status": "done", "job": "figures-0001-a1", "error": null,
 "figures": "<output_dir>/figures.json", "leaves": [1, 2, 3]}
```

`figures.json` rows carry the catalog's region fields, with `leaf` for `page`, `bbox` as `[x0, y0, x1, y1]` and
`crop` (the file name in `output_dir`) for `image_path`. `band: review` is what the page studio shows as a disputed
region. Only a broken message or input fails the job: a leaf without an image, a region naming a leaf the message
does not list, an output outside `STORAGE_PATH`, or the delivery cap. Then the job writes `status: failed` with
`error` and raises, so `link_error` fires. An invalid message that names a safe outcome path gets a `failed` outcome
too. A deliberate requeue (SIGTERM) writes nothing, so the redelivery keeps the token.

The job is an [evilflowers-worker](https://github.com/EvilFlowersCatalog/evilflowers-worker) leaf job
(`FiguresJob(LeafJob[RegionsJob, list[Region]])`, design in the kit's `docs/architecture.md`). The kit runs the
lifecycle; this service writes `extract` (crop, gate, caption) and `publish` (`/regions`):

1. **Delivery cap.** A message delivered more than `MAX_DELIVERIES` (5) times killed its worker every time. It is
   reported `failed` instead of run again.
2. **Run check.** `GET runs/<id>` before the work. A copy of a job already reported (`already_done`), a run no longer
   running (`not_running`) or a superseded attempt (`superseded`) stops before anything is cropped. Between regions
   the job checks again every 5 minutes, so a long book with captions stops when the run moves on.
3. **The job always reports `done` or `failed`**, because a run finishes only when every declared job has reported. An
   empty batch (`regions: []`) reports `done` too. A region that fails is logged and skipped. The job fails when the
   PDF cannot be opened, `output_dir` points outside `STORAGE_PATH`, or the catalog rejects the results.
4. **A 409 is the exception.** The catalog no longer wants the results, and the job stops quietly (`superseded` is
   reported as such and counted). Crops already written stay until the catalog deletes the run's folder.

Every crop path is resolved under `STORAGE_PATH` (`storage_file`, which refuses `..`, absolute paths and escaping
symlinks) and written atomically (`.partial`, fsync, rename), so a half-written crop never exists.

PaliGemma and the ViT/ResNet labellers of the earlier prototype are gone. Captions come from a multimodal LLM
(IP-018 Q8), which on a CPU host means an Ollama endpoint. Which model to use is still open, and captions are off in
dev.

## Layout

```
src/evilflowers_image/
├── worker.py          Celery app (`celery -A evilflowers_image.worker worker`): the kit's `create_app("image", …)`
├── tasks.py           both tasks: `run_job(…FiguresJob…)` and `run_task(…StandaloneFigures…)`
├── jobs.py            `FiguresJob`: extract (crop, gate, decide, caption) and publish
├── standalone.py      `StandaloneFiguresJob`, its outcome file and `figures.json`
├── figures.py         gates and the two passes: regions → crops → decided figures
├── decisions.py       `FIGURE_KIND`, the perceptual hash and the repeated-image check, the process's judges
├── crops.py           page sources (PDF, leaf images), rendering, WebP names and atomic writes
├── captions.py        the Ollama captioner and the answer parser
├── metrics.py         the figures' own metrics (regions, caption duration)
└── settings.py        `Settings(WorkerSettings, JudgeSettings)`: the figures' own fields
docs/diagrams/         `sequence-figure-decision` (.puml, .svg, .png) and the ELVIRA theme copy
```

The Celery configuration, the catalog client, the job protocol, shutdown, the delivery cap and observability are all
evilflowers-worker's, pinned to a commit in `pyproject.toml` (`[tool.uv.sources]`). To move the pin, change `rev` and
run `uv lock --upgrade-package evilflowers-worker`.

## Development

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.12. The `otel` extra adds the OpenTelemetry SDK, and
the `profiling` extra adds the Pyroscope SDK.

```bash
make install        # core + dev tools (ruff, pytest): enough for the tests
make check          # ruff check, ruff format --check, pytest (TEST_REDIS_URL for the real-worker tests)
make install-all    # everything the image has
make worker         # a local worker (REDIS_URL, STORAGE_PATH, CATALOG_API_* from .env)
make image          # docker build, tagged evilflowers-image-service:local
docker compose up --build    # Redis + image
```

To bump a dependency, run `uv lock --upgrade-package <name>`. `pymupdf` stays below 2: version 2.x hard-depends on
onnxruntime and a layout model, and this worker only renders crops.

Tests use the kit's `evilflowers_worker.testing`. `test_jobs.py` runs the job against `FakeCatalog`;
`test_decisions.py` and `test_standalone.py` fake decider-vision at the HTTP level (`conftest.FakeDecider`).
`test_end_to_end.py` runs a real prefork worker (`WorkerProcess`) against Redis (`TEST_REDIS_URL`, default
`redis://localhost:6379/15`; `docker compose up -d redis`) and a `StubCatalogServer`. It covers the batch job name,
`?attempt=`, an empty batch, and a book that kills its worker ending `failed` after `MAX_DELIVERIES`. It also covers
a standalone job firing `link` on success and `link_error` on failure, with no result backend. Without Redis these
tests are skipped, except in CI, where they fail.

## Configuration

All settings are environment variables. `.env.sample` lists them, and `src/evilflowers_image/settings.py` has their
defaults and meaning. The ones a deployment sets:

- `REDIS_URL`
- `BROKER_VISIBILITY_TIMEOUT`: 43200 (the default), one value for every consumer of the Redis db
- `WORKER_SOFT_SHUTDOWN_TIMEOUT` (60) and `WORKER_CANCEL_TIMEOUT` (30). Their sum must stay under the pod's
  `terminationGracePeriodSeconds`.
- `MAX_DELIVERIES` (5)
- `STORAGE_PATH`, the catalog's storage root, mounted read/write
- `CATALOG_API_URL` and `CATALOG_API_KEY`, the key of a catalog user holding `extraction.ingest_extraction`
- `CAPTIONS_ENABLED`, `OLLAMA_ENDPOINT`, `OLLAMA_API_KEY` and `CAPTION_MODEL`, only when captions are on
- `DECIDER_ENABLED`, `DECIDER_VISION_URL` (`http://decider-vision.shared.svc.cluster.local`) and `DECIDER_TIMEOUT`
  (knowledge `Cookbooks/Deploy-Decision-Models`). Add `JUDGE_THRESHOLDS` once knowledge#65 has measured them. Leaving
  them empty turns the decider off.
- `IMAGE_TAG`, built in by CI. It is recorded in the run's provenance and used as `service.version`.

The standalone Deployment (knowledge#66) is the same image with `IMAGE_STANDALONE=1`, `REDIS_URL` on the
digitalizer's db (`…/8` on dev), `STORAGE_PATH` on the library mount and no `CATALOG_API_*`. It consumes
`evilflowers_image.standalone.interactive` and `evilflowers_image.standalone`. The always-on interactive replica adds
`-Q evilflowers_image.standalone.interactive`, and the KEDA-scaled one `-Q evilflowers_image.standalone`. Its spans
carry `evilflowers.digitalizer.run_id` / `job_id`.

## Build and deploy

`.github/workflows/docker-publish.yml` follows the text service's workflow:

| Event | Result |
|---|---|
| push to `develop` | test, push `ghcr.io/evilflowerscatalog/evilflowers-image-service:develop` + `:sha-<short>`, **deploy to `evilflowers-dev`** |
| push to `main` | test, push `:main` + `:sha-<short>` |
| tag `v*.*.*` | test, push `:<version>` + `:sha-<short>` |
| pull request | test, build (no push) |

The `deploy` job runs on the self-hosted runner inside k3s (`runs-on: elvira-k3s`; knowledge base,
`Cookbooks/CI-Runner`). It restarts `deployment/image` and waits for the rollout. It fails unless every running pod
uses the digest it just pushed. The first deploy needs the dev instance pinned to `:develop` and this repo in the
runner group (EvilFlowersCatalog/knowledge#20).

The image's start command is `celery -A evilflowers_image.worker worker --loglevel=INFO -E --concurrency=1`, on the
prefork pool; the settings choose the queues (`IMAGE_QUEUE`, or the standalone pair). With one child, Flower can still inspect the worker during a long
book, which it cannot do with `--pool=solo`. The image also ships a one-line `/app/src/worker.py` shim, so the dev
manifest's old `celery --workdir src -A worker …` args keep working until knowledge#20 changes them.

### Shutdown and scale-in

KEDA scales the worker on its Redis list, so a pod can get SIGTERM in the middle of a book. Shutdown is
evilflowers-worker's (`evilflowers_worker.shutdown`), and nothing in the image or the manifest may set `REMAP_SIGTERM`:

1. An idle worker exits at once.
2. A running book goes on for up to `WORKER_SOFT_SHUTDOWN_TIMEOUT` seconds. If it finishes, it is acknowledged and the
   worker exits, so a finished book is not done again.
3. Otherwise the job is cancelled. The message is not yet acknowledged, so it goes straight back on
   `evilflowers_image` instead of waiting out `BROKER_VISIBILITY_TIMEOUT`. If the cancel takes longer than
   `WORKER_CANCEL_TIMEOUT`, the worker requeues the message itself and exits.

A deliberate requeue does not count towards `MAX_DELIVERIES`; a worker that dies (OOM) does. The kit's own test suite
checks this against a real Redis.

## Observability

The service follows the cluster's telemetry contract (knowledge base, `Cookbooks/Deploy-a-Service` §3). Everything is
off unless the pod points it at a collector, and it starts in `worker_process_init`, so in the prefork child that runs
the task.

- **Traces.** Every task gets a CONSUMER span that continues the caller's `traceparent`. Every catalog or Ollama call
  gets a CLIENT span that carries it on, except the Ollama calls: there is one per figure, so they have no spans,
  which keeps the trace of a book with many batches under Tempo's size limit. The hand-made span is `figures.extract`
  (regions in, figures kept). The endpoint comes from `OTEL_EXPORTER_OTLP_ENDPOINT`, or from `HOST_IP` when only that is set;
  with neither, tracing is off. Sampling follows `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG`
  (`parentbased_traceidratio` in k8s). A failed job marks its span as an error.
- **Metrics** (Mimir):
  - `image_task_duration_seconds`
  - `image_job_outcome_total{job,outcome}`, where `job` is the kind (`figures`), never a batch name, and `outcome`
    is `done`, `failed`, `not_running`, `superseded` or `already_done`
  - `image_deliveries_capped_total`
  - `image_figures_regions_total{outcome}` (`kept`, `repeated`, `too_small`, `extreme_aspect_ratio`,
    `covers_the_page`, `error`)
  - `image_judge_total{question="figure_kind",outcome,band}` (`judged`, `disabled`, `budget`, `open`, `unreachable`,
    `refused`, `invalid`) and `image_judge_seconds`, from the kit's `judges`
  - `image_caption_duration_seconds{model,outcome}`
  - `image_catalog_retries_total{route,reason}`
  - process CPU and memory
- **Logs.** Each log line is one JSON object on stdout, with `level`, `trace_id`/`span_id`, `task_name`/`task_id`
  and the job's `run_id`, `job`, `attempt`, `delivery` and `source`. Set `LOG_FORMAT=text` for a terminal.
- **Profiles** (Pyroscope). The node's eBPF profiler cannot unwind Python on k3s `control`, so the worker profiles
  itself with the Pyroscope SDK when `PYROSCOPE_SERVER_ADDRESS` is set. `PYROSCOPE_APPLICATION_NAME` defaults to
  `image`, and `PYROSCOPE_TAGS` takes `k=v` pairs separated by commas. Each trace's root span links to its profile.

Queries:

```
Tempo:     {resource.service.name="image" && kind=consumer}
Tempo:     {resource.service.name="image" && span.evilflowers.extraction.run_id="<run uuid>"}
Loki:      {service_name="image"} | json | run_id="<run uuid>"
Pyroscope: {service_name="image", namespace="evilflowers-dev"}
```
