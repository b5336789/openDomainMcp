from opendomainmcp.models import ENTITY_TYPES, RELATION_TYPES, KnowledgeUnit
from opendomainmcp.graph.models import Entity, Edge


def test_vocab_contains_expected_terms():
    assert "Component" in ENTITY_TYPES and "Concept" in ENTITY_TYPES
    assert "depends_on" in RELATION_TYPES and "related_to" in RELATION_TYPES


def test_knowledge_unit_has_graph_fields_defaulting_empty():
    k = KnowledgeUnit()
    assert k.entities == []
    assert k.typed_relations == []
    assert k.is_empty() is True  # graph fields must not change emptiness semantics


def test_entity_and_edge_dataclasses():
    e = Entity(normalized_name="auth service", display_name="Auth Service",
               type="Service", chunk_id="c1")
    assert e.confidence == 1.0
    edge = Edge(src="auth service", dst="user db", relation_type="depends_on", chunk_id="c1")
    assert edge.confidence == 1.0
