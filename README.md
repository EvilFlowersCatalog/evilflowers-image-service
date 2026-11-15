# EvilFlowers Image Service

The Celery worker that handles the figures of an IP-018 extraction run (Intelligent Viewer, catalog
`docs/proposals/posts/ip-018-intelligent-viewer.md`). For each figure region that `evilflowers-analyzer-service`'s
layout pass found, it writes a WebP crop, drops slivers and full-page scans, optionally asks a multimodal model for a
description and a category, and posts the result to
[EvilFlowersCatalog](https://github.com/EvilFlowersCatalog/EvilFlowersCatalog). No model runs in this process.

## Task

The task name, queue and argument shape are a contract with their callers (`tests/test_worker.py` guards it).

| Task | Queue | Sent by | Does |
|---|---|---|---|
| `evilflowers_image.figures` | `evilflowers_image` (`IMAGE_QUEUE`) | analyzer, kwargs `run_id, source, output_dir, regions[, job, attempt]` (`RegionsJob`) | Crops, gates and optionally describes each figure region. Posts the kept ones to `/regions`, then reports `/jobs/<job>`. |

`regions` is `[{page, seq, bbox: {x0, y0, x1, y1}, caption}]`: page fractions with a top-left origin on the 1-based
page. `caption` is the caption printed in the document, if the analyzer found one. `job` is the catalog job to report
under: a layout batch such as `figures:0001-0008`, or `figures` when absent. `attempt` comes from the catalog's
`/start`; it goes back as `?attempt=` on every write. Unknown kwargs are ignored. For each region the job:

1. renders the box at `CROP_DPI` (144);
2. drops it if its shorter side is under `MIN_SIDE_PX` (80), its aspect ratio is over `MAX_ASPECT_RATIO` (8), or it
   covers more than `MAX_PAGE_COVERAGE` (0.9) of the page;
3. writes `<STORAGE_PATH>/<output_dir>/p012-fig03.webp` (`WEBP_QUALITY` 82);
4. with `CAPTIONS_ENABLED`, sends a thumbnail and the printed caption to an Ollama endpoint (`OLLAMA_ENDPOINT`,
   `/api/chat`, `format: json`, model `CAPTION_MODEL`). The answer is `description` and one `category` (`chart`,
   `diagram`, `photo`, `map`, `drawing`, `screenshot`, `other`). A failing caption keeps the crop.

Each region is posted with `kind: figure`, `image_path`, `bbox`, `printed_caption`, `description`, `category` and
`caption` (`printed_caption or description`, kept for catalogs that predate the split).

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
├── tasks.py           the `evilflowers_image.figures` task: `run_job(self, FiguresJob, RegionsJob, kwargs)`
├── jobs.py            `FiguresJob`: extract (crop, gate, caption) and publish
├── figures.py         gates and one region → one figure (crop, optional caption)
├── crops.py           page geometry, rendering, WebP names and atomic writes
├── captions.py        the Ollama captioner and the answer parser
├── metrics.py         the figures' own metrics (regions, caption duration)
└── settings.py        `Settings(WorkerSettings)`: the figures' own fields
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

Tests use the kit's `evilflowers_worker.testing`. `test_jobs.py` runs the job against `FakeCatalog`.
`test_end_to_end.py` runs a real prefork worker (`WorkerProcess`) against Redis (`TEST_REDIS_URL`, default
`redis://localhost:6379/15`; `docker compose up -d redis`) and a `StubCatalogServer`. It covers the batch job name,
`?attempt=`, an empty batch, and a book that kills its worker ending `failed` after `MAX_DELIVERIES`. Without Redis
these tests are skipped, except in CI, where they fail.

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
- `IMAGE_TAG`, built in by CI. It is recorded in the run's provenance and used as `service.version`.

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

The image's start command is `celery -A evilflowers_image.worker worker --loglevel=INFO -E --concurrency=1
--queues=evilflowers_image`, on the prefork pool. With one child, Flower can still inspect the worker during a long
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
  - `image_figures_regions_total{outcome}` (`kept`, `too_small`, `extreme_aspect_ratio`, `covers_the_page`, `error`)
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
