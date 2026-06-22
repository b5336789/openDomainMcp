# Graph-Augmented Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an `ask` question names a knowledge-graph entity (or matches a workflow), inject that entity's edges / the workflow's ordered steps into the RAG context as one extra cited source, so relation/sequence questions are answerable.

**Architecture:** A new pure module `query/graph_context.py` deterministically seeds entity names from the question's identifiers and the top chunks' `symbol`s, confirms them against the graph, and renders their `neighbors()` edges + any matching `get_workflow()` steps as a single synthetic `SearchResult` (`kind="graph"`). `query/rag.py` appends it — only after the relevance floor passes — behind a new `retrieve_include_graph` setting. `NullGraphStore` makes it a no-op.

**Tech Stack:** Python 3.11, pydantic-settings, existing `graph/` store (MariaDB / NullGraphStore), pytest.

## Global Constraints

- Off by default: `retrieve_include_graph: bool = False`; `NullGraphStore` → no-op.
- No LLM and no network beyond the graph store in the graph path.
- Graph augmentation is best-effort: `build_graph_context` must never raise outward (catch, log, return `None`).
- Graph is appended **after** `_apply_relevance_floor`, so it can never rescue an out-of-corpus refusal or enable fabrication.
- Caps: `_MAX_ENTITIES = 3`, `_MAX_EDGES = 8` (per entity), `_MAX_CHARS = 1500`.
- Graph API shapes (verbatim):
  - `get_entity(name) -> {"name", "normalized_name", "type", "confidence"} | None`
  - `neighbors(name, relation_type=None) -> {"entity": {...}|None, "neighbors": [{"entity": {"name","normalized_name","type"}, "relation_type": str, "direction": "out"|"in"}]}` (direction `"out"` = root is src)
  - `list_workflows(q=...) -> [{"name": str}]`
  - `get_workflow(name) -> {"prerequisites": [str], "steps": [{"order": int, "text": str, "precondition": str}]} | None`
- Chunk `SearchResult.metadata` carries `symbol` (an entity name) but **not** `entities`.

---

## File Structure

- Create `src/opendomainmcp/query/graph_context.py` — entity seeding + edge/workflow rendering → `SearchResult | None`.
- Modify `src/opendomainmcp/config.py` — add `retrieve_include_graph` field + `EDITABLE_FIELDS` entry.
- Modify `src/opendomainmcp/query/rag.py` — `graph=None` param on both answer fns; `_source_label` + `_citations` graph branches; the append hook.
- Modify `src/opendomainmcp/cli.py`, `src/opendomainmcp/api/app.py`, `src/opendomainmcp/server.py` — pass `graph=ctx.graph`.
- Modify `.env.example` — document `ODM_RETRIEVE_INCLUDE_GRAPH`.
- Create `tests/test_graph_context.py`; modify `tests/test_rag.py`.
- Measure on `benchmarks/erpnext`; update its README findings.

---

### Task 1: Config flag `retrieve_include_graph`

**Files:**
- Modify: `src/opendomainmcp/config.py` (the `EDITABLE_FIELDS` tuple ~line 27-43; the settings block after `retrieve_include_graph`'s sibling `retrieve_min_score` ~line 107-115)
- Modify: `.env.example` (after `ODM_RETRIEVE_MIN_SCORE`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.retrieve_include_graph: bool` (default `False`), present in `EDITABLE_FIELDS`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_config.py`:

```python
def test_retrieve_include_graph_defaults_off_and_is_editable():
    from opendomainmcp.config import EDITABLE_FIELDS, Settings
    assert Settings().retrieve_include_graph is False
    assert Settings(retrieve_include_graph=True).retrieve_include_graph is True
    assert "retrieve_include_graph" in EDITABLE_FIELDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_retrieve_include_graph_defaults_off_and_is_editable -v`
Expected: FAIL (`AttributeError`/ValidationError — field missing).

- [ ] **Step 3: Add the field and editable entry.** In `config.py`, after the `retrieve_min_score` field add:

```python
    # Include a knowledge-graph relations source (matched entity edges + any
    # matching workflow steps) in the ask context. Off or NullGraphStore == today.
    retrieve_include_graph: bool = False
```

And add `"retrieve_include_graph",` to the `EDITABLE_FIELDS` tuple (after `"retrieve_min_score",`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py::test_retrieve_include_graph_defaults_off_and_is_editable -v`
Expected: PASS

- [ ] **Step 5: Document in `.env.example`** — after the `ODM_RETRIEVE_MIN_SCORE` block:

```bash
# Inject a knowledge-graph source into 'ask': when the question names a graph
# entity (or matches a workflow), its edges / ordered steps are added as one
# cited source. Answers relation/sequence questions the chunks don't cover.
# Off by default; no-op when the graph is unwired (NullGraphStore).
ODM_RETRIEVE_INCLUDE_GRAPH=false
```

- [ ] **Step 6: Commit**

```bash
git add src/opendomainmcp/config.py .env.example tests/test_config.py
git commit -m "feat(config): add retrieve_include_graph setting (default off)"
```

---

### Task 2: `query/graph_context.py` — build the graph source

**Files:**
- Create: `src/opendomainmcp/query/graph_context.py`
- Test: `tests/test_graph_context.py`

**Interfaces:**
- Consumes: graph store with `get_entity`, `neighbors`, `list_workflows`, `get_workflow` (shapes in Global Constraints); `SearchResult` from `..models`.
- Produces: `build_graph_context(graph, query, chunk_results, settings) -> SearchResult | None`. Returned `SearchResult` has `metadata={"kind": "graph", "title": str}`, `score=0.0`, `id` starting `"graph:"`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_graph_context.py`:

```python
from opendomainmcp.config import Settings
from opendomainmcp.models import SearchResult
from opendomainmcp.query.graph_context import build_graph_context


class FakeGraph:
    """Minimal graph: entities by name, out-edges, and one workflow."""
    def __init__(self, entities=None, edges=None, workflows=None):
        self._entities = entities or {}            # name -> type
        self._edges = edges or {}                  # name -> [(rel, dst)]
        self._workflows = workflows or {}          # name -> {prerequisites, steps}

    def get_entity(self, name):
        t = self._entities.get(name)
        return {"name": name, "normalized_name": name.lower(), "type": t} if t else None

    def neighbors(self, name, relation_type=None, depth=1):
        if name not in self._entities:
            return {"entity": None, "neighbors": []}
        nbrs = [{"entity": {"name": dst, "normalized_name": dst.lower(), "type": "Function"},
                 "relation_type": rel, "direction": "out"}
                for rel, dst in self._edges.get(name, [])]
        return {"entity": {"name": name}, "neighbors": nbrs}

    def list_workflows(self, q=None, limit=50):
        return [{"name": n} for n in self._workflows]

    def get_workflow(self, name):
        return self._workflows.get(name)


def _chunk(symbol):
    return SearchResult(id=symbol, text="x", score=0.6,
                        metadata={"source": "f.py", "symbol": symbol})


def test_entity_named_in_question_yields_edge_lines():
    g = FakeGraph(entities={"calculate_taxes": "Function"},
                  edges={"calculate_taxes": [("calls", "adjust_grand_total_for_inclusive_tax")]})
    r = build_graph_context(g, "which function does calculate_taxes call?", [], Settings())
    assert r is not None
    assert r.metadata["kind"] == "graph"
    assert "calculate_taxes" in r.text and "adjust_grand_total_for_inclusive_tax" in r.text
    assert "calls" in r.text


def test_seeds_from_top_chunk_symbols():
    g = FakeGraph(entities={"set_discount_amount": "Function"},
                  edges={"set_discount_amount": [("uses", "apply_discount_on")]})
    # question does not name the entity; a retrieved chunk's symbol does
    r = build_graph_context(g, "how is the document discount applied?",
                            [_chunk("set_discount_amount")], Settings())
    assert r is not None and "apply_discount_on" in r.text


def test_workflow_query_yields_ordered_steps():
    g = FakeGraph(workflows={"tax calculation": {
        "prerequisites": ["conversion rate set"],
        "steps": [{"order": 2, "text": "calculate taxes", "precondition": ""},
                  {"order": 1, "text": "calculate net total", "precondition": ""}]}})
    r = build_graph_context(g, "order of steps in tax calculation", [], Settings())
    assert r is not None
    i1, i2 = r.text.find("calculate net total"), r.text.find("calculate taxes")
    assert 0 <= i1 < i2  # steps rendered in 'order', not input order


def test_no_match_returns_none():
    g = FakeGraph(entities={"calculate_taxes": "Function"})
    assert build_graph_context(g, "how does payroll withholding work?", [], Settings()) is None


def test_stopwords_not_treated_as_entities():
    g = FakeGraph(entities={"function": "Concept"}, edges={"function": [("rel", "x")]})
    # 'function'/'which' are stopwords; must not seed even though graph has them
    assert build_graph_context(g, "which function returns the value?", [], Settings()) is None


def test_graph_errors_yield_none():
    class Boom:
        def get_entity(self, name): raise RuntimeError("db down")
        def neighbors(self, *a, **k): raise RuntimeError("db down")
        def list_workflows(self, *a, **k): raise RuntimeError("db down")
        def get_workflow(self, *a, **k): raise RuntimeError("db down")
    assert build_graph_context(Boom(), "calculate_taxes calls what?", [], Settings()) is None


def test_char_cap_respected():
    edges = {"big": [("calls", f"dst_{i}") for i in range(50)]}
    g = FakeGraph(entities={"big": "Function"}, edges=edges)
    r = build_graph_context(g, "what does big call?", [], Settings())
    assert r is not None and len(r.text) <= 1500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_graph_context.py -v`
Expected: FAIL (`ModuleNotFoundError: opendomainmcp.query.graph_context`).

- [ ] **Step 3: Implement the module.** Create `src/opendomainmcp/query/graph_context.py`:

```python
"""Graph-augmented retrieval context for the ask path.

Deterministically finds the knowledge-graph entities a question names (plus the
entities behind the top retrieved chunks' symbols) and renders their edges and
any matching workflow's ordered steps as a single synthetic SearchResult. No
LLM, no network beyond the graph store, and best-effort: any failure yields None
so a graph problem never breaks chunk-based answering.
"""
from __future__ import annotations

import logging
import re

from ..models import SearchResult

logger = logging.getLogger(__name__)

_MAX_ENTITIES = 3
_MAX_EDGES = 8
_MAX_CHARS = 1500

# Common question words that are not entity references. Confirmation via
# get_entity plus the entity cap bound spurious matches, so this only covers
# obvious noise — it need not be exhaustive.
_STOPWORDS = {
    "which", "does", "what", "when", "where", "how", "function", "functions",
    "value", "values", "method", "methods", "calls", "call", "step", "steps",
    "order", "system", "rule", "rules", "used", "field", "fields", "return",
    "returns", "with", "that", "this", "from", "into", "the", "and", "for",
}


def _candidate_names(query: str) -> list[str]:
    """Identifier-like tokens a question might use to name a graph entity:
    backtick/quote-delimited spans, then snake_case / CamelCase / dotted tokens,
    then plain words of length >= 4 that aren't stopwords."""
    names: list[str] = []
    for m in re.finditer(r"[`\"']([^`\"']+)[`\"']", query):
        names.append(m.group(1).strip())
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", query):
        looks_id = ("_" in tok) or ("." in tok) or any(c.isupper() for c in tok[1:])
        if looks_id or (len(tok) >= 4 and tok.lower() not in _STOPWORDS):
            names.append(tok)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n.strip())
    return out


def _seed_entities(graph, query: str, chunk_results) -> list[dict]:
    """Confirmed graph entities seeded from question identifiers and the top
    chunks' symbols. Capped at _MAX_ENTITIES; each confirmed via get_entity."""
    seeds: list[dict] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name or len(seeds) >= _MAX_ENTITIES:
            return
        ent = graph.get_entity(name)
        if not ent:
            return
        key = (ent.get("normalized_name") or ent.get("name") or name).lower()
        if key not in seen:
            seen.add(key)
            seeds.append(ent)

    for name in _candidate_names(query):
        if len(seeds) >= _MAX_ENTITIES:
            break
        add(name)
    for r in chunk_results[:3]:
        if len(seeds) >= _MAX_ENTITIES:
            break
        add((r.metadata or {}).get("symbol"))
    return seeds


def _edge_lines(graph, entity: dict) -> list[str]:
    """`src —rel→ dst` lines for one entity's neighbours (both directions)."""
    name = entity.get("name") or entity.get("normalized_name")
    result = graph.neighbors(name) or {}
    lines: list[str] = []
    for nb in result.get("neighbors", []):
        other = (nb.get("entity") or {}).get("name")
        rel = nb.get("relation_type") or "related_to"
        if not other:
            continue
        if nb.get("direction") == "in":
            lines.append(f"{other} —{rel}→ {name}")
        else:
            lines.append(f"{name} —{rel}→ {other}")
        if len(lines) >= _MAX_EDGES:
            break
    return lines


def _workflow_lines(graph, query: str) -> list[str]:
    """Ordered steps + prerequisites of the first workflow matching the query."""
    matches = graph.list_workflows(q=query) or []
    if not matches:
        return []
    wf = graph.get_workflow(matches[0].get("name"))
    if not wf:
        return []
    lines = [f"Workflow: {matches[0].get('name')}"]
    for p in wf.get("prerequisites", []):
        lines.append(f"  prerequisite: {p}")
    for s in sorted(wf.get("steps", []), key=lambda s: s.get("order", 0)):
        text = (s.get("text") or "").strip()
        if text:
            lines.append(f"  step {s.get('order')}: {text}")
    return lines if len(lines) > 1 else []


def build_graph_context(graph, query: str, chunk_results, settings) -> SearchResult | None:
    """One synthetic SearchResult (kind='graph') with the matched entities'
    edges and any matching workflow's steps, or None when nothing matches or the
    graph errors."""
    try:
        seeds = _seed_entities(graph, query, chunk_results)
        lines: list[str] = []
        titles: list[str] = []
        for ent in seeds:
            elines = _edge_lines(graph, ent)
            if elines:
                titles.append(ent.get("name") or "")
                lines.extend(elines)
        lines.extend(_workflow_lines(graph, query))
        if not lines:
            return None
        text = "\n".join(lines)[:_MAX_CHARS]
        title = "Knowledge graph: " + (", ".join(t for t in titles if t) or "workflow")
        return SearchResult(id=f"graph:{abs(hash(text))}", text=text, score=0.0,
                            metadata={"kind": "graph", "title": title})
    except Exception as exc:  # best-effort: a graph problem must not break ask
        logger.warning("graph context unavailable (%r); skipping", exc)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_graph_context.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add src/opendomainmcp/query/graph_context.py tests/test_graph_context.py
git commit -m "feat(query): build graph-relations context source for ask"
```

---

### Task 3: Wire the graph source into `rag.py`

**Files:**
- Modify: `src/opendomainmcp/query/rag.py` (`_source_label`, `_citations`, `answer_question`, `answer_question_stream`)
- Test: `tests/test_rag.py`

**Interfaces:**
- Consumes: `build_graph_context` (Task 2); `Settings.retrieve_include_graph` (Task 1).
- Produces: `answer_question(query, store, settings, top_k=6, synthesize=None, graph=None)` and `answer_question_stream(query, store, settings, top_k=6, synthesize_stream=None, graph=None)`; a `kind="graph"` source is appended (after the floor) when the flag is on, the graph is non-None, and a context is built. Its citation has `type="graph"`, `symbol=None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rag.py`. Reuse the `_ScoredStore` / `FakeGraph` patterns:

```python
def test_graph_source_appended_when_enabled():
    from opendomainmcp.models import SearchResult
    from tests.test_graph_context import FakeGraph

    store = _ScoredStore([SearchResult(id="c", text="chunk", score=0.72,
                                       metadata={"source": "f.py", "symbol": "x"})])
    g = FakeGraph(entities={"calculate_taxes": "Function"},
                  edges={"calculate_taxes": [("calls", "adjust_grand_total_for_inclusive_tax")]})
    settings = Settings(retrieve_include_articles=False, retrieve_include_graph=True)
    captured = {}

    def synth(model, system, user):
        captured["user"] = user
        return "calc calls adjust [2]"

    result = answer_question("what does calculate_taxes call?", store, settings,
                             synthesize=synth, graph=g)
    assert "adjust_grand_total_for_inclusive_tax" in captured["user"]  # graph block reached the model
    types = {c["type"] for c in result["citations"]}
    assert "graph" in types
    graph_cite = next(c for c in result["citations"] if c["type"] == "graph")
    assert graph_cite["symbol"] is None


def test_graph_source_absent_when_flag_off():
    from opendomainmcp.models import SearchResult
    from tests.test_graph_context import FakeGraph

    store = _ScoredStore([SearchResult(id="c", text="chunk", score=0.72,
                                       metadata={"source": "f.py", "symbol": "x"})])
    g = FakeGraph(entities={"calculate_taxes": "Function"},
                  edges={"calculate_taxes": [("calls", "adjust")]})
    settings = Settings(retrieve_include_articles=False, retrieve_include_graph=False)
    result = answer_question("what does calculate_taxes call?", store, settings,
                             synthesize=lambda *a: "x [1]", graph=g)
    assert all(c["type"] != "graph" for c in result["citations"])


def test_graph_not_consulted_when_floor_refuses():
    from opendomainmcp.models import SearchResult
    from tests.test_graph_context import FakeGraph

    store = _ScoredStore([SearchResult(id="c", text="chunk", score=0.40,
                                       metadata={"source": "f.py"})])
    g = FakeGraph(entities={"calculate_taxes": "Function"},
                  edges={"calculate_taxes": [("calls", "adjust")]})
    settings = Settings(retrieve_include_articles=False, retrieve_include_graph=True,
                        retrieve_min_score=0.65)
    called = []
    result = answer_question("what does calculate_taxes call?", store, settings,
                             synthesize=lambda *a: called.append(1) or "x", graph=g)
    assert result["citations"] == [] and not called  # refused before graph
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rag.py -k graph -v`
Expected: FAIL (`answer_question` has no `graph` kwarg / no graph citation).

- [ ] **Step 3: Add the `_source_label` graph branch.** In `rag.py`, in `_source_label`, before the `loc = meta.get("source", "?")` fallback:

```python
    if meta.get("kind") == "graph":
        return meta.get("title") or "Knowledge graph"
```

- [ ] **Step 4: Add the `_citations` graph branch.** In `_citations`, change the `if is_article:` chain to also handle graph:

```python
        kind = r.metadata.get("kind")
        if kind == "article":
            source = _source_label(r)
            symbol = None
            type_ = "article"
        elif kind == "graph":
            source = _source_label(r)
            symbol = None
            type_ = "graph"
        else:
            source = r.metadata.get("source", "?")
            symbol = r.metadata.get("symbol")
            type_ = "chunk"
```

(Remove the now-replaced `is_article = ...` line.)

- [ ] **Step 5: Add the `graph` param + append hook to both functions.** In `answer_question`, change the signature to `def answer_question(query, store, settings, top_k: int = 6, synthesize=None, graph=None) -> dict:` and, right after `if not results:` returns the refusal, before building `user`, insert:

```python
    if getattr(settings, "retrieve_include_graph", False) and graph is not None:
        from .graph_context import build_graph_context
        gc = build_graph_context(graph, query, results, settings)
        if gc is not None:
            results = results + [gc]
```

Apply the identical signature change (`graph=None`) and the identical block to `answer_question_stream` (insert after its `if not results:` refusal `return`, before `user = ...`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_rag.py -k graph -v`
Expected: PASS (3 new). Then `python -m pytest tests/test_rag.py -v` — all pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add src/opendomainmcp/query/rag.py tests/test_rag.py
git commit -m "feat(rag): append graph-relations source to ask when enabled"
```

---

### Task 4: Pass `ctx.graph` from the surfaces

**Files:**
- Modify: `src/opendomainmcp/server.py:79`, `src/opendomainmcp/cli.py:65`, `src/opendomainmcp/api/app.py:118` and `:139`
- Test: `tests/test_rag.py` (a wiring assertion via the api test client is optional; the unit tests in Task 3 already cover behavior)

**Interfaces:**
- Consumes: `answer_question(..., graph=)` / `answer_question_stream(..., graph=)` from Task 3; `ctx.graph` from `build_context`.

- [ ] **Step 1: Pass the graph in each caller.**
  - `server.py:79`: `return answer_question(query, ctx.store, ctx.settings, top_k=top_k, graph=ctx.graph)`
  - `cli.py:65`: add `graph=ctx.graph` to the `answer_question_stream(...)` call.
  - `api/app.py:118`: `result = answer_question(req.query, ctx.store, ctx.settings, top_k=req.top_k, graph=ctx.graph)`
  - `api/app.py:139`: add `graph=ctx.graph` to the `answer_question_stream(...)` call.

- [ ] **Step 2: Run the full suite to verify no regressions**

Run: `python -m pytest -q`
Expected: PASS (all green; the existing api/cli/mcp ask tests still pass — `NullGraphStore`/flag-off path is unchanged).

- [ ] **Step 3: Commit**

```bash
git add src/opendomainmcp/server.py src/opendomainmcp/cli.py src/opendomainmcp/api/app.py
git commit -m "feat(surfaces): pass ctx.graph to ask for graph-augmented retrieval"
```

---

### Task 5: Measure on the ERPNext benchmark + document

**Files:**
- Modify: `benchmarks/erpnext/README.md` (the findings/fix section)
- No source changes.

**Interfaces:** none (measurement + docs).

- [ ] **Step 1: Ensure the clean `erpnext` collection exists.** If needed:

Run: `./run.sh --collection erpnext stats`
Expected: ~134 chunks. (If absent, `benchmarks/erpnext/setup_corpus.sh` first.)

- [ ] **Step 2: Baseline (graph off).**

Run: `.venv/bin/python benchmarks/erpnext/run_benchmark.py --collection erpnext --out benchmarks/erpnext/graph-off.report.json`
Record `retrieval_hit_rate` and the `FAILED retrieval` list (expect `gr2` among them).

- [ ] **Step 3: Graph on.**

Run: `ODM_RETRIEVE_INCLUDE_GRAPH=true .venv/bin/python benchmarks/erpnext/run_benchmark.py --collection erpnext --out benchmarks/erpnext/graph-on.report.json`

Note: `run_benchmark.py` calls `answer_question(q, store, settings, top_k)` without `graph=`. For this measurement to exercise the graph path, update `run_benchmark.py`'s `ask`/`retrieve` closures to pass `graph=ctx.graph` (it already builds `ctx = build_context(...)`; capture `ctx.graph`). This is a benchmark-harness change, commit it with the docs.

- [ ] **Step 4: Compare and record.** Diff the two reports' `missing` sets. Update `benchmarks/erpnext/README.md`: add a row to the findings showing graph-off vs graph-on retrieval_hit_rate and which cases flipped (expect `gr2`; note honestly whether `wf1`/`ex1` moved).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/erpnext/README.md benchmarks/erpnext/run_benchmark.py
git commit -m "test(benchmarks): measure graph-augmented retrieval (before/after)"
```

---

## Self-Review

**Spec coverage:** Problem/Goal → Tasks 2-3 (build + wire); Components 1 (graph_context) → Task 2; Component 2 (rag hook + `_source_label`/`_citations`) → Task 3; Component 3 (callers) → Task 4; Component 4 (settings) → Task 1; Data flow / floor-ordering → Task 3 Step 5 + `test_graph_not_consulted_when_floor_refuses`; Error handling (best-effort None) → Task 2 `test_graph_errors_yield_none`; Testing → Tasks 2-3 tests + Task 5 benchmark. **Deviation from spec:** chunk-entity seeding is replaced by chunk-**symbol** seeding because chunk metadata carries `symbol`, not `entities` (verified) — same intent (seed from retrieved chunks), real metadata.

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `build_graph_context(graph, query, chunk_results, settings) -> SearchResult | None` used identically in Task 2 (def) and Task 3 (call). Graph source `metadata={"kind":"graph","title":...}` consistent across `graph_context.py`, `_source_label`, `_citations`, and tests. `answer_question(..., graph=None)` signature consistent in Tasks 3 and 4.
