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
| `evilflowers_image.figures` | `evilflowers_image` (`IMAGE_QUEUE`) | analyzer, kwargs `run_id, source, output_dir, regions` | Crops, gates and optionally describes each figure region. Posts the kept ones to `/regions`, then reports `/jobs/figures`. |

`regions` is `[{page, seq, bbox: {x0, y0, x1, y1}, caption}]`: page fractions with a top-left origin on the 1-based
page. `caption` is the caption printed in the document, if the analyzer found one. Unknown kwargs are ignored. For
each region the job:

1. renders the box at `CROP_DPI` (144);
2. drops it if its shorter side is under `MIN_SIDE_PX` (80), its aspect ratio is over `MAX_ASPECT_RATIO` (8), or it
   covers more than `MAX_PAGE_COVERAGE` (0.9) of the page;
3. writes `<STORAGE_PATH>/<output_dir>/p012-fig03.webp` (`WEBP_QUALITY` 82);
4. with `CAPTIONS_ENABLED`, sends a thumbnail and the printed caption to an Ollama endpoint (`OLLAMA_ENDPOINT`,
   `/api/chat`, `format: json`, model `CAPTION_MODEL`). The answer is `description` and one `category` (`chart`,
   `diagram`, `photo`, `map`, `drawing`, `screenshot`, `other`). A failing caption keeps the crop.

Each region is posted with `kind: figure`, `image_path`, `bbox`, `printed_caption`, `description`, `category` and
`caption` (`printed_caption or description`, kept for catalogs that predate the split).

The job follows the IP-018 protocol of the sibling services (`jobs.FiguresJob.run`):

- **The job always reports `done` or `failed`**, because a run finishes only when every declared job has
  reported. A region that fails is logged and skipped. The job fails when the PDF cannot be opened or the catalog
  rejects the results.
- **A 409 is the exception.** It means the catalog no longer accepts the run, and the job stops quietly. Crops
  already written stay until the catalog deletes the run's folder.
- **Late acknowledgement** (`acks_late`, `reject_on_worker_lost`). If the worker dies mid-book, the message is
  delivered again.

PaliGemma and the ViT/ResNet labellers of the earlier prototype are gone. Captions come from a multimodal LLM
(IP-018 Q8), which on a CPU host means an Ollama endpoint. Which model to use is still open, and captions are off in
dev.

## Layout

```
src/evilflowers_image/
├── worker.py          Celery app (`celery -A evilflowers_image.worker worker`), config and routes
├── tasks.py           the `evilflowers_image.figures` task (thin adapter)
├── jobs.py            the IP-018 job protocol (extract → publish → report) for figures
├── figures.py         gates and one region → one figure (crop, optional caption)
├── crops.py           page geometry, rendering, WebP names and writes
├── captions.py        the Ollama captioner and the answer parser
├── settings.py        typed settings from the environment (pydantic-settings)
├── clients/           catalog ingestion API, shared HTTP session
└── observability/     OpenTelemetry setup, spans, metrics, JSON logs, Pyroscope profiling, Celery signal wiring
```

It is the same layout as `evilflowers-text-service`. `observability/` is a copy of the text service's, with the
`image` names.

## Development

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.12. The `otel` extra adds the OpenTelemetry SDK, and
the `profiling` extra adds the Pyroscope SDK.

```bash
make install        # core + dev tools (ruff, pytest): enough for the tests
make check          # ruff check, ruff format --check, pytest
make install-all    # everything the image has
make worker         # a local worker (REDIS_URL, STORAGE_PATH, CATALOG_API_* from .env)
make image          # docker build, tagged evilflowers-image-service:local
docker compose up --build    # Redis + image
```

To bump a dependency, run `uv lock --upgrade-package <name>`. `pymupdf` stays below 2: version 2.x hard-depends on
onnxruntime and a layout model, and this worker only renders crops.

## Configuration

All settings are environment variables. `.env.sample` lists them, and `src/evilflowers_image/settings.py` has their
defaults and meaning. The ones a deployment sets:

- `REDIS_URL`
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

## Observability

The service follows the cluster's telemetry contract (knowledge base, `Cookbooks/Deploy-a-Service` §3). Everything is
off unless the pod points it at a collector, and it starts in `worker_process_init`, so in the prefork child that runs
the task.

- **Traces.** Every task gets a CONSUMER span that continues the caller's `traceparent`. Every catalog or Ollama call
  gets a CLIENT span that carries it on. Hand-made spans cover `figures.extract` (regions in, figures kept) and each
  `figures.caption`. The endpoint comes from `OTEL_EXPORTER_OTLP_ENDPOINT`, or from `HOST_IP` when only that is set;
  with neither, tracing is off. Sampling follows `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG`
  (`parentbased_traceidratio` in k8s). A failed job marks its span as an error.
- **Metrics** (Mimir):
  - `image_task_duration_seconds`
  - `image_job_outcome_total{job,outcome}` (`done`, `failed`, `not_running`)
  - `image_figures_regions_total{outcome}` (`kept`, `too_small`, `extreme_aspect_ratio`, `covers_the_page`, `error`)
  - `image_caption_duration_seconds{model,outcome}`
  - `image_catalog_retries_total`
  - process CPU and memory
- **Logs.** Each log line is one JSON object on stdout, with `level`, `trace_id`/`span_id`, `task_name`/`task_id`
  and the job's `run_id`, `job` and `source`. Set `LOG_FORMAT=text` for a terminal.
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
