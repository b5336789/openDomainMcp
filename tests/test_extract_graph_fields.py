from opendomainmcp.extract.knowledge import _parse


def test_parse_extracts_typed_entities_and_relations():
    raw = '''{
      "summary": "s", "concepts": ["a"], "relations": ["A -> B"],
      "knowledge_type": "Architecture", "audience": ["engineering"],
      "confidence": 0.9, "version": "", "tags": [], "permissions": [], "references": [],
      "entities": [{"name": "Auth Service", "type": "Service"},
                   {"name": "User DB", "type": "Resource"}],
      "typed_relations": [{"src": "Auth Service", "dst": "User DB", "type": "depends_on"}]
    }'''
    k = _parse(raw)
    assert k.entities == [{"name": "Auth Service", "type": "Service"},
                          {"name": "User DB", "type": "Resource"}]
    assert k.typed_relations == [
        {"src": "Auth Service", "dst": "User DB", "type": "depends_on"}]


def test_parse_clamps_unknown_types_to_fallback():
    raw = '''{"summary": "s", "knowledge_type": "API", "audience": [],
      "entities": [{"name": "X", "type": "Bogus"}],
      "typed_relations": [{"src": "X", "dst": "Y", "type": "frobnicates"}]}'''
    k = _parse(raw)
    assert k.entities == [{"name": "X", "type": "Concept"}]  # unknown -> Concept
    assert k.typed_relations == [{"src": "X", "dst": "Y", "type": "related_to"}]


def test_parse_drops_malformed_entities():
    raw = '''{"summary": "s", "audience": [],
      "entities": [{"type": "Service"}, {"name": "", "type": "Service"}, "junk"],
      "typed_relations": [{"src": "A", "type": "calls"}]}'''
    k = _parse(raw)
    assert k.entities == []          # missing/empty name dropped
    assert k.typed_relations == []   # missing dst dropped
