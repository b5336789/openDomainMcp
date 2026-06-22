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
    then plain words of length >= 3 that aren't stopwords."""
    names: list[str] = []
    for m in re.finditer(r"[`\"']([^`\"']+)[`\"']", query):
        names.append(m.group(1).strip())
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", query):
        looks_id = ("_" in tok) or ("." in tok) or any(c.isupper() for c in tok[1:])
        if looks_id or (len(tok) >= 3 and tok.lower() not in _STOPWORDS):
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
