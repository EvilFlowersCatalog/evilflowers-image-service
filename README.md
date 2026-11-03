# evilflowers-image-service

Figures of an extraction run (IP-018 Intelligent Viewer, catalog
`docs/proposals/posts/ip-018-intelligent-viewer.md`).

`evilflowers_image.figures` (queue `evilflowers_image`) receives the figure regions found by
`evilflowers-analyzer-service`'s layout pass: `run_id`, `source`, `output_dir` and
`regions: [{page, seq, bbox, caption}]` (page fractions, top-left origin). For each region it:

1. crops the page area to WebP at `CROP_DPI` into `<STORAGE_PATH>/<output_dir>/p012-fig03.webp`
   and keeps the bounding box;
2. drops regions under `MIN_SIDE_PX` on a side, beyond `MAX_ASPECT_RATIO`, or covering more than
   `MAX_PAGE_COVERAGE` of the page;
3. when `CAPTIONS_ENABLED`, asks a multimodal model behind an Ollama endpoint (`CAPTION_MODEL`) for a
   short description and a category (`chart`, `diagram`, `photo`, `map`, `drawing`, `screenshot`,
   `other`); otherwise the caption printed in the document is kept.

Regions and the `figures` job are reported to the catalog's `/extraction/v1/runs/{run_id}/...`
(`src/catalog.py`). A failing region is skipped; the job fails only when the PDF cannot be opened.

PaliGemma and the ViT/ResNet labellers of the earlier prototype are gone: captions come from a
multimodal LLM (IP-018 Q8), which on a CPU host means an Ollama endpoint. Which model is still open.

See `.env.sample` for the settings. CI publishes `ghcr.io/evilflowerscatalog/evilflowers-image-service`
(`:main` on `main`, semver tags on `v*.*.*`).
