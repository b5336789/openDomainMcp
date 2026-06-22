# Cheaper Extraction: Haiku + Batch API — Design

Date: 2026-06-23
Status: Approved (pending spec review)

## Problem

Knowledge extraction (`extract/knowledge.py`) makes one Anthropic Messages call
per chunk during ingestion (default model `claude-sonnet-4-6`). For large
corpora this is the dominant API cost. We want to lower it via two independent
levers, and we evaluated a third that turned out to be a no-op.

## Three levers — what we keep

| Lever | Verdict | Why |
|---|---|---|
| **#2 Cheaper model (Haiku 4.5)** | **Ship — config only** | `extraction_model` is already a runtime-editable setting (`config.py`). Setting `ODM_EXTRACTION_MODEL=claude-haiku-4-5` makes extraction 3–5× cheaper ($1/$5 vs $3/$15 per 1M tok). No code. We document it. |
| **#4 Prompt caching** | **Drop — no-op** | The extraction `_SYSTEM` prompt is ~500 tokens. Anthropic's minimum cacheable prefix is 2048 tok (Sonnet 4.6) / 4096 tok (Haiku 4.5). A prefix below the minimum silently does not cache (`cache_creation_input_tokens == 0`). The only cacheable prefix here is that short system prompt (the user message — the chunk — is unique every call), so `cache_control` would save nothing. Fail Loud: don't ship a no-op. |
| **#3 Batch API** | **Build** | The Message Batches API runs the same requests at 50% of standard price. This is the real implementation work and the rest of this doc. |

## #3 Batch API — design

### Constraint that shapes everything

The Batches API is **asynchronous**: submit a batch, poll until
`processing_status == "ended"` (usually < 1 h, max 24 h), then read results.
This conflicts with the current ingest flow, which is synchronous, streams
per-stage progress, and runs `load → split → extract → embed → store` per file
in `_ingest_file`. The chosen approach (whole-corpus single batch, synchronous
block-and-poll) batches **all** chunks of one `ingest_path` run together for
maximum savings, and blocks (with progress) until the batch ends.

### Integration approach: minimal-invasion pre-pass + CachedExtractor

We do **not** restructure the proven `_ingest_file` per-file flow. Instead:

1. **Extract `_load_and_split(path) -> list[Chunk]`** from `_ingest_file` (a
   pure refactor: the existing load + split logic, lines ~154–188, moved to a
   helper called by both `_ingest_file` and the pre-pass — removes the
   duplication a pre-pass would otherwise introduce).
2. **Pre-pass** (only when batch enabled): in `_ingest()`, after the file list
   is gathered and filtered, walk those files with `_load_and_split`, collect
   the text of every chunk that needs extraction (skip pre-classified chunks
   that already carry a `knowledge_type`), and call
   `BatchExtractor.extract_many` once for the whole set → a
   `{text_hash: KnowledgeUnit}` cache.
3. **Swap the extractor for the per-file loop**: wrap the real extractor in a
   `CachedExtractor(cache, fallback)` and assign it to `self._extractor` inside
   a `try/finally` (restored afterward) for the duration of the run. The
   existing per-file loop (`_ingest_file` → `_extract_all` → `_extract_one`)
   runs unchanged; each `extract(text, …)` call now resolves from the cache.

Cost of this choice: `load + split` runs twice (once in the pre-pass, once in
the real loop). That is **local CPU/IO only — no API cost** — and it keeps the
core ingestion flow untouched (Surgical Changes). Chunk text is deterministic,
so the `text_hash` computed in both passes matches.

### New unit: `ingest/batch_extract.py`

```
BatchExtractor(client, model, max_tokens=900, poll_interval=10.0)
    extract_many(items: list[BatchItem], progress=None) -> dict[str, KnowledgeUnit]
```

- `BatchItem` carries `text_hash` (custom_id), `text`, `kind`, `language`.
- Builds one `Request(custom_id=text_hash, params=MessageCreateParamsNonStreaming(
  model=..., max_tokens=..., system=_SYSTEM, messages=[{role:"user",
  content: f"Snippet type: {label}\n\n{text}"}]))` per item — reusing the exact
  `_SYSTEM` and message shape from `ClaudeExtractor.extract` so batch and
  non-batch produce identical extractions.
- `client.messages.batches.create(requests=...)`, then poll
  `client.messages.batches.retrieve(id)` every `poll_interval` seconds until
  `processing_status == "ended"`, emitting progress
  (`request_counts.processing/succeeded/errored`).
- Stream `client.messages.batches.results(id)`; for each result keyed by
  `custom_id`: `succeeded` → `_parse(message text)` → `KnowledgeUnit` into the
  map; `errored`/`canceled`/`expired` → omit from the map (chunk becomes a cache
  miss → CachedExtractor falls back to one live call).
- De-dup: identical chunk texts share a `custom_id`; the batch carries each
  unique text once. (Anthropic requires unique `custom_id` per request.)
- `client` is injectable → fully offline tests (fake `batches` namespace).

### New wrapper: `CachedExtractor`

```python
class CachedExtractor:
    def __init__(self, cache: dict[str, KnowledgeUnit], fallback):
        self._cache, self._fallback = cache, fallback
    def extract(self, text, kind, language=None) -> KnowledgeUnit:
        hit = self._cache.get(_text_hash(text))
        return hit if hit is not None else self._fallback.extract(text, kind, language)
```

`_text_hash(text)` = `sha256(text.encode()).hexdigest()` — shared helper used by
both the pre-pass collector and `CachedExtractor` so keys always agree.

### Configuration (`config.py`)

- New setting `extract_batch: bool = False` (`ODM_EXTRACT_BATCH`), added to
  `EDITABLE_FIELDS` alongside the other `extract_*` flags (it is ingestion
  behavior, not a credential).
- `.env.example`: document `ODM_EXTRACT_BATCH` **and** add the Haiku note next to
  `ODM_EXTRACTION_MODEL` (lever #2).

### Gating (Fail Loud)

- Batch is **Anthropic-only**. If `extract_batch` is true but
  `settings.llm_backend.lower() != "anthropic"`, raise a clear error at the start
  of the batch pre-pass (the OpenAI/local batch API is a different surface, out of
  scope). Do not silently fall back to sync.
- `extract_batch` false → zero behavior change; the pre-pass and CachedExtractor
  are never constructed.
- Empty corpus / no extractable chunks → no batch submitted.

### Error handling (Fail Loud)

- Per-request failure inside the batch → recorded in `report.errors`; that chunk
  is a cache miss and is re-extracted by one live fallback call (best-effort,
  consistent with the existing per-chunk failure policy).
- Batch submit/poll API errors → propagate (do not silently degrade to sync).

## Data flow (batch mode)

```
ingest_path(dir)
  → _ingest(): gather + filter files
    → BATCH PRE-PASS (extract_batch on):
        for f in files: chunks = _load_and_split(f)
        collect {text_hash: (text, kind, language)} for chunks needing extraction
        BatchExtractor.extract_many(items) → cache {text_hash: KnowledgeUnit}
      swap self._extractor = CachedExtractor(cache, real_extractor)  [try/finally]
    → for f in files: _ingest_file(f)        # unchanged
        load → split → _extract_all (now cache lookups) → prune → embed → store
```

## Files touched

- `src/opendomainmcp/ingest/batch_extract.py` — new: `BatchExtractor`,
  `CachedExtractor`, `BatchItem`, `_text_hash`.
- `src/opendomainmcp/ingest/pipeline.py` — extract `_load_and_split`; add the
  batch pre-pass + extractor swap in `_ingest`; build `BatchExtractor` from the
  Anthropic client when gated on.
- `src/opendomainmcp/config.py` — `extract_batch` setting + `EDITABLE_FIELDS`.
- `.env.example` — document `ODM_EXTRACT_BATCH` and the Haiku option.
- `tests/test_batch_extract.py` — new: BatchExtractor + CachedExtractor.
- `tests/test_pipeline.py` (or a new test file) — batch pre-pass wiring +
  Fail-Loud gating on non-anthropic backend.

## Scope / YAGNI

- No two-phase submit/collect commands; synchronous block-and-poll only.
- No OpenAI/local batch support.
- No prompt caching (lever #4 — proven no-op for this prompt size).
- No change to the default extraction model (Haiku is opt-in via env).
- No caching of split results between the two passes (re-split is cheap, local).

## Cost impact

- Lever #2 alone (Haiku): ~3–5× cheaper extraction.
- Lever #3 alone (Batch): 50% off.
- Combined: ~6–10× cheaper than the Sonnet-4.6 synchronous baseline, traded
  against an asynchronous ingest that blocks for minutes-to-~1h on large corpora.
