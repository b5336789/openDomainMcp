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
