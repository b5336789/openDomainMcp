"""Turn a chunk's extracted KnowledgeUnit into graph nodes and edges.

Entities declared in ``knowledge.entities`` carry an explicit type; any
relation endpoint not declared as an entity is added as a ``Concept`` so the
edge always connects two real nodes.
"""

from __future__ import annotations

from ..models import KnowledgeUnit
from .models import Edge, Entity
from .normalize import normalize_name


def build_graph(knowledge: KnowledgeUnit, chunk_id: str) -> tuple[list[Entity], list[Edge]]:
    entities: dict[str, Entity] = {}

    def _add(name: str, type_: str) -> str:
        norm = normalize_name(name)
        if not norm:
            return ""
        if norm not in entities:
            entities[norm] = Entity(normalized_name=norm, display_name=name.strip(),
                                    type=type_, chunk_id=chunk_id,
                                    confidence=knowledge.confidence or 1.0)
        return norm

    for ent in knowledge.entities:
        _add(ent.get("name", ""), ent.get("type", "Concept"))

    edges: list[Edge] = []
    for rel in knowledge.typed_relations:
        src = _add(rel.get("src", ""), "Concept")
        dst = _add(rel.get("dst", ""), "Concept")
        if src and dst:
            edges.append(Edge(src=src, dst=dst, relation_type=rel.get("type", "related_to"),
                              chunk_id=chunk_id, confidence=knowledge.confidence or 1.0))

    return list(entities.values()), edges
