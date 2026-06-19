# Final Review Fixes — Graph/Vector Desync

## Fix 1: `delete_item` orphaned graph rows

**File:** `src/opendomainmcp/api/app.py` (`delete_item` endpoint, ~line 282)

After `ctx.store.delete_item(item_id)` returns truthy (item existed), now also calls:
```python
ctx.graph.delete_for_chunks([item_id])
```
The 404 path is unchanged — graph pruning only happens when the store confirmed deletion.

## Fix 2: `create_item` wrote chunks with no graph rows

**File:** `src/opendomainmcp/api/app.py` (`create_item` endpoint, ~line 239)

After `ctx.store.upsert([chunk])`, now mirrors the pipeline's `_write_graph` logic:
```python
if chunk.knowledge and not chunk.knowledge.is_empty():
    entities, edges = build_graph(chunk.knowledge, chunk.id)
    ctx.graph.upsert_entities(entities)
    ctx.graph.upsert_edges(edges)
```
`build_graph` is imported locally (same pattern as other modules in the file). Manually-authored chunks today have no `entities`/`typed_relations`, so this typically writes nothing — but the path is now correct and future-proof, consistent with ingest.

## Tests Added (`tests/test_graph_api.py`)

- `test_delete_item_prunes_graph`: Creates a chunk in `store`, upserts a matching Entity (by `chunk.id`) in `fake_graph`, confirms entity present, DELETEs via API, asserts entity is pruned. Passes for the right reason — the endpoint calls `ctx.graph.delete_for_chunks([item_id])`.
- `test_delete_item_missing_returns_404`: DELETEs a non-existent id, asserts 404.

### Intentionally Skipped Test

`test_create_item_with_entities_writes_graph` — skipped. The `ItemCreate` API body has no `entities` or `typed_relations` fields; manually-authored knowledge always produces an empty entity list from `build_graph`. There is no end-to-end path to exercise entity writes via the API without either modifying the request schema (out of scope) or constructing a contrived test that bypasses the endpoint. The Fix 2 code path is correct and mirrors the pipeline exactly; it will be exercised naturally once the API schema accepts entity declarations.

## Commands Run and Output

```
source .venv/bin/activate && ODM_EXTRACT_KNOWLEDGE=true python -m pytest tests/test_graph_api.py -v
# 8 passed, 2 warnings in 0.57s

source .venv/bin/activate && ODM_EXTRACT_KNOWLEDGE=true python -m pytest -q
# 164 passed, 1 skipped, 2 warnings in 1.85s
```
