# Entity Graph 基礎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為知識庫加上有型別的實體圖（entities/edges），在每-chunk 萃取時順帶抽取、持久化到 MariaDB，並透過 API/MCP 查詢。

**Architecture:** LLM 知識萃取在現有單次呼叫中疊加 `entities`/`typed_relations` 兩欄位；`graph/` 模組把它們正規化為 nodes/edges 寫進 MariaDB（PyMySQL）；圖與向量（Chroma）同生命週期增量同步；查詢層提供純讀的 API 端點與 MCP 工具。

**Tech Stack:** Python 3.11+、PyMySQL、MariaDB、pydantic-settings、FastAPI、pytest、Chroma（既有，不動）。

## Global Constraints

- 圖儲存後端為 **MariaDB**，driver 用 **PyMySQL**（純 Python）。
- MariaDB 為**全平台必需**：`build_context()` 啟動時連線並 `ensure_schema()`，連不上即 **fail-loud**（清楚錯誤訊息）。
- 向量仍存 **Chroma**，本子專案**不遷移**。
- 新增欄位/型別**全部疊加且帶預設**，舊索引與 `NullExtractor` 須維持有效。
- 既有自由文字 `concepts`/`relations` **保留不動**。
- 型別白名單未知值 **clamp 到 fallback**（`related_to` / `Concept`），**不** fail-loud。
- 測試基線：全套件 ≥ 既有 **133** 綠燈；新邏輯純單元測試零外部服務；MariaDB 測試標 `@pytest.mark.integration`，需 `graph_db_*` 環境變數才跑。
- `ENTITY_TYPES = ("Component","Service","Function","Class","API","Concept","Person/Team","Resource")`
- `RELATION_TYPES = ("depends_on","calls","owns","part_of","uses","related_to")`
- `list_related_entities` 的 `depth` 預設 1、**上限 2**。

---

## File Structure

| 檔案 | 職責 | 動作 |
|------|------|------|
| `src/opendomainmcp/models.py` | 型別詞彙 + `KnowledgeUnit` 新欄位 | Modify |
| `src/opendomainmcp/graph/__init__.py` | 模組匯出 | Create |
| `src/opendomainmcp/graph/models.py` | `Entity` / `Edge` dataclasses | Create |
| `src/opendomainmcp/graph/normalize.py` | 純正規化函式 | Create |
| `src/opendomainmcp/graph/builder.py` | KnowledgeUnit → nodes/edges | Create |
| `src/opendomainmcp/graph/store.py` | `GraphStoreProtocol` / `MariaGraphStore` / `NullGraphStore` | Create |
| `src/opendomainmcp/extract/knowledge.py` | prompt/parse 疊加 entities/typed_relations | Modify |
| `src/opendomainmcp/config.py` | `graph_db_*` 設定欄位 | Modify |
| `src/opendomainmcp/ingest/pipeline.py` | upsert/prune 同步圖 | Modify |
| `src/opendomainmcp/context.py` | 接線 GraphStore（fail-loud） | Modify |
| `src/opendomainmcp/api/app.py` | `/api/graph/*` 端點 | Modify |
| `src/opendomainmcp/server.py` | MCP graph 工具 | Modify |
| `tests/conftest.py` | `FakeExtractor` 延伸 + `FakeGraphStore` fixture | Modify |
| `pyproject.toml` | 加 `pymysql` 依賴 | Modify |
| `.env.example` | `graph_db_*` 範例 | Modify |

---

## Task 1: 型別詞彙、KnowledgeUnit 欄位、圖資料模型

**Files:**
- Modify: `src/opendomainmcp/models.py`
- Create: `src/opendomainmcp/graph/__init__.py`
- Create: `src/opendomainmcp/graph/models.py`
- Test: `tests/test_graph_models.py`

**Interfaces:**
- Consumes: 既有 `KnowledgeUnit`（`models.py`）。
- Produces:
  - `ENTITY_TYPES: tuple[str, ...]`、`RELATION_TYPES: tuple[str, ...]`（`models.py`）
  - `KnowledgeUnit.entities: list[dict]`（每筆 `{"name": str, "type": str}`）
  - `KnowledgeUnit.typed_relations: list[dict]`（每筆 `{"src": str, "dst": str, "type": str}`）
  - `graph.models.Entity(normalized_name, display_name, type, chunk_id, confidence=1.0)`
  - `graph.models.Edge(src, dst, relation_type, chunk_id, confidence=1.0)`（`src`/`dst` 皆為 normalized_name）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_models.py -v`
Expected: FAIL — `ImportError` (no `ENTITY_TYPES` / `opendomainmcp.graph`).

- [ ] **Step 3: Add vocab + fields to `models.py`**

在 `models.py` 的 `AUDIENCES = (...)` 之後新增：

```python
# Entity/relation vocabularies for the knowledge graph (single source of truth
# shared by the extractor prompt and the graph builder). Keep in sync.
ENTITY_TYPES = (
    "Component", "Service", "Function", "Class", "API",
    "Concept", "Person/Team", "Resource",
)

RELATION_TYPES = (
    "depends_on", "calls", "owns", "part_of", "uses", "related_to",
)
```

在 `KnowledgeUnit` 的 `review_status: str = "approved"` 之後新增兩欄位：

```python
    # Structured graph material extracted alongside the free-form concepts/
    # relations. Each entity is {"name", "type"}; each relation is
    # {"src", "dst", "type"}. Default empty so older indexes stay valid.
    entities: list[dict] = field(default_factory=list)
    typed_relations: list[dict] = field(default_factory=list)
```

> `is_empty()` 與 `metadata()` **不要**改 —— 圖欄位是疊加，不影響 emptiness 或 Chroma metadata。

- [ ] **Step 4: Create `graph/__init__.py` and `graph/models.py`**

```python
# src/opendomainmcp/graph/__init__.py
"""Knowledge graph: typed entities and relations persisted in MariaDB."""

from .models import Edge, Entity

__all__ = ["Entity", "Edge"]
```

```python
# src/opendomainmcp/graph/models.py
"""Plain dataclasses for graph nodes and edges (no business logic)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Entity:
    normalized_name: str
    display_name: str
    type: str
    chunk_id: str
    confidence: float = 1.0


@dataclass
class Edge:
    src: str  # normalized_name of source entity
    dst: str  # normalized_name of destination entity
    relation_type: str
    chunk_id: str
    confidence: float = 1.0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_graph_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/opendomainmcp/models.py src/opendomainmcp/graph/__init__.py src/opendomainmcp/graph/models.py tests/test_graph_models.py
git commit -m "feat(graph): entity/relation vocab, KnowledgeUnit fields, graph dataclasses"
```

---

## Task 2: 萃取疊加 entities/typed_relations

**Files:**
- Modify: `src/opendomainmcp/extract/knowledge.py:22-40` (`_SYSTEM`), `:67-96` (`_parse`), `:107` (`max_tokens` 預設)
- Modify: `tests/conftest.py:64-85` (`FakeExtractor`)
- Test: `tests/test_extract_graph_fields.py`

**Interfaces:**
- Consumes: `ENTITY_TYPES`、`RELATION_TYPES`、`KnowledgeUnit`（Task 1）。
- Produces: `ClaudeExtractor.extract(...)` 回傳的 `KnowledgeUnit` 帶正規化過的 `entities`/`typed_relations`；`FakeExtractor` 同樣回傳它們。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract_graph_fields.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extract_graph_fields.py -v`
Expected: FAIL — `_parse` does not set `entities`/`typed_relations` (AssertionError).

- [ ] **Step 3: Extend `_SYSTEM` prompt**

在 `extract/knowledge.py` 的 `_SYSTEM` 字串，於 `"references"` 那一行之後（`.\n"` 結尾之前）插入兩個新 key 描述。把現有結尾：

```python
    '  "references": a list of external identifiers it cites such as URLs, ticket '
    "or error codes (may be empty).\n"
    "Do not include any prose outside the JSON object."
```

改為：

```python
    '  "references": a list of external identifiers it cites such as URLs, ticket '
    "or error codes (may be empty),\n"
    '  "entities": a list of {"name", "type"} for the key entities, each type one of '
    + ", ".join(ENTITY_TYPES) + " (may be empty),\n"
    '  "typed_relations": a list of {"src", "dst", "type"} directed relations '
    "between entity names, each type one of "
    + ", ".join(RELATION_TYPES) + " (may be empty).\n"
    "Do not include any prose outside the JSON object."
```

並更新 import：把 `from ..models import AUDIENCES, KNOWLEDGE_TYPES, KnowledgeUnit` 改為：

```python
from ..models import (
    AUDIENCES,
    ENTITY_TYPES,
    KNOWLEDGE_TYPES,
    RELATION_TYPES,
    KnowledgeUnit,
)
```

- [ ] **Step 4: Add parse helpers + wire into `_parse`**

在 `_norm_choice` 之後新增 fallback 版本與兩個結構化解析器：

```python
def _norm_choice_default(value, allowed: tuple[str, ...], default: str) -> str:
    """Like _norm_choice but falls back to ``default`` instead of '' for
    unknown values (the model occasionally invents type names)."""
    return _norm_choice(value, allowed) or default


def _parse_entities(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if not isinstance(v, dict):
            continue
        name = str(v.get("name", "")).strip()
        if not name:
            continue
        out.append({"name": name,
                    "type": _norm_choice_default(v.get("type", ""), ENTITY_TYPES, "Concept")})
    return out


def _parse_relations(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if not isinstance(v, dict):
            continue
        src, dst = str(v.get("src", "")).strip(), str(v.get("dst", "")).strip()
        if not src or not dst:
            continue
        out.append({"src": src, "dst": dst,
                    "type": _norm_choice_default(v.get("type", ""), RELATION_TYPES, "related_to")})
    return out
```

在 `_parse` 的 `KnowledgeUnit(...)` 建構，於 `references=...` 之後新增兩個欄位：

```python
        references=_str_list(data.get("references", [])),
        entities=_parse_entities(data.get("entities", [])),
        typed_relations=_parse_relations(data.get("typed_relations", [])),
    )
```

- [ ] **Step 5: Bump `max_tokens` default**

`ClaudeExtractor.__init__` 的 `max_tokens: int = 600` 改為 `max_tokens: int = 900`（容納結構化欄位）。

- [ ] **Step 6: Extend `FakeExtractor` in conftest**

`tests/conftest.py` 的 `FakeExtractor.extract` 回傳的 `KnowledgeUnit(...)` 新增兩欄位（於 `version="1.0.0",` 之後）：

```python
            version="1.0.0",
            entities=[{"name": first_word or kind, "type": "Concept"}],
            typed_relations=[],
        )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_extract_graph_fields.py -v && pytest -q`
Expected: 新測試 PASS；全套件仍綠燈（≥133，新測試使數字增加）。

- [ ] **Step 8: Commit**

```bash
git add src/opendomainmcp/extract/knowledge.py tests/conftest.py tests/test_extract_graph_fields.py
git commit -m "feat(extract): emit typed entities/relations in single extraction call"
```

---

## Task 3: 正規化與圖建構（純邏輯）

**Files:**
- Create: `src/opendomainmcp/graph/normalize.py`
- Create: `src/opendomainmcp/graph/builder.py`
- Test: `tests/test_graph_builder.py`

**Interfaces:**
- Consumes: `KnowledgeUnit`（Task 1）、`Entity`/`Edge`（Task 1）。
- Produces:
  - `graph.normalize.normalize_name(name: str) -> str`
  - `graph.builder.build_graph(knowledge: KnowledgeUnit, chunk_id: str) -> tuple[list[Entity], list[Edge]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_builder.py
from opendomainmcp.models import KnowledgeUnit
from opendomainmcp.graph.normalize import normalize_name
from opendomainmcp.graph.builder import build_graph


def test_normalize_name_lowercases_and_collapses_whitespace():
    assert normalize_name("  Auth   Service ") == "auth service"


def test_build_graph_produces_entities_and_edges():
    k = KnowledgeUnit(
        entities=[{"name": "Auth Service", "type": "Service"}],
        typed_relations=[{"src": "Auth Service", "dst": "User DB", "type": "depends_on"}],
    )
    entities, edges = build_graph(k, chunk_id="c1")
    by_norm = {e.normalized_name: e for e in entities}
    # declared entity keeps its type; relation endpoint not declared -> Concept
    assert by_norm["auth service"].type == "Service"
    assert by_norm["auth service"].display_name == "Auth Service"
    assert by_norm["user db"].type == "Concept"
    assert len(edges) == 1
    assert (edges[0].src, edges[0].dst, edges[0].relation_type) == (
        "auth service", "user db", "depends_on")
    assert edges[0].chunk_id == "c1"


def test_build_graph_dedupes_entities_by_normalized_name():
    k = KnowledgeUnit(entities=[{"name": "Auth Service", "type": "Service"},
                                {"name": "auth service", "type": "Concept"}])
    entities, _ = build_graph(k, chunk_id="c1")
    assert len([e for e in entities if e.normalized_name == "auth service"]) == 1


def test_build_graph_empty_knowledge_yields_nothing():
    entities, edges = build_graph(KnowledgeUnit(), chunk_id="c1")
    assert entities == [] and edges == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_builder.py -v`
Expected: FAIL — `ImportError` (modules not created).

- [ ] **Step 3: Implement `normalize.py`**

```python
# src/opendomainmcp/graph/normalize.py
"""Deterministic name normalization for graph entities."""

from __future__ import annotations


def normalize_name(name: str) -> str:
    """Lowercase, trim, and collapse internal whitespace.

    The normalized form is the dedup/lookup key; the first-seen original is
    kept as the display name.
    """
    return " ".join(str(name).lower().split())
```

- [ ] **Step 4: Implement `builder.py`**

```python
# src/opendomainmcp/graph/builder.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_graph_builder.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/opendomainmcp/graph/normalize.py src/opendomainmcp/graph/builder.py tests/test_graph_builder.py
git commit -m "feat(graph): deterministic normalize + build nodes/edges from KnowledgeUnit"
```

---

## Task 4: GraphStore（MariaDB）、Protocol、NullGraphStore、設定

**Files:**
- Create: `src/opendomainmcp/graph/store.py`
- Modify: `src/opendomainmcp/config.py:43-92` (Settings 欄位)
- Modify: `src/opendomainmcp/graph/__init__.py`
- Modify: `pyproject.toml:12-38` (依賴)
- Modify: `.env.example`
- Modify: `tests/conftest.py` (新增 `FakeGraphStore` + fixture)
- Test: `tests/test_graph_store_fake.py`、`tests/test_graph_store_mariadb.py`

**Interfaces:**
- Consumes: `Entity`/`Edge`（Task 1）、`Settings`（config）。
- Produces:
  - `graph.store.GraphStoreProtocol`，方法：`ensure_schema() -> None`、`upsert_entities(entities: list[Entity]) -> None`、`upsert_edges(edges: list[Edge]) -> None`、`delete_for_chunks(chunk_ids: Iterable[str]) -> None`、`get_entity(name: str) -> dict | None`、`neighbors(name: str, relation_type: str | None = None, depth: int = 1) -> dict`
  - `graph.store.MariaGraphStore(host, port, user, password, database)`
  - `graph.store.NullGraphStore`（全 no-op，供未接線情境）
  - `get_entity` 回傳：`{"name", "normalized_name", "type", "aliases": list[str], "chunk_ids": list[str], "confidence": float}` 或 `None`
  - `neighbors` 回傳：`{"entity": <get_entity dict>, "neighbors": [{"entity": {...}, "relation_type": str, "direction": "out"|"in"}]}`（找不到實體時 `entity` 為 `None`、`neighbors` 為 `[]`）
  - 測試 fixture：`fake_graph`（`FakeGraphStore` 實例）

- [ ] **Step 1: Add `pymysql` dependency**

`pyproject.toml` 的 `dependencies = [...]` 內，於 `"chromadb>=0.5",` 之後加一行：

```python
    "pymysql>=1.1",
```

執行 `pip install -e .`（或 `uv pip install pymysql`）讓環境有 driver。

- [ ] **Step 2: Add config fields**

`config.py` 的 `Settings` 內，於 `max_retries: int = 2` 之後新增（沿用既有 `Field`/型別風格）：

```python
    # --- Knowledge graph store (MariaDB, required platform-wide) ---
    graph_db_host: str = "localhost"
    graph_db_port: int = 3306
    graph_db_user: str = "opendomain"
    graph_db_password: str = ""
    graph_db_name: str = "opendomain_graph"
```

`.env.example` 結尾新增：

```bash
# --- Knowledge graph store (MariaDB, required) ---
GRAPH_DB_HOST=localhost
GRAPH_DB_PORT=3306
GRAPH_DB_USER=opendomain
GRAPH_DB_PASSWORD=
GRAPH_DB_NAME=opendomain_graph
```

- [ ] **Step 3: Write the failing test (Protocol parity via FakeGraphStore)**

```python
# tests/test_graph_store_fake.py
from opendomainmcp.graph.models import Edge, Entity


def test_fake_graph_upsert_get_and_neighbors(fake_graph):
    fake_graph.upsert_entities([
        Entity("auth service", "Auth Service", "Service", "c1"),
        Entity("user db", "User DB", "Resource", "c1"),
    ])
    fake_graph.upsert_edges([Edge("auth service", "user db", "depends_on", "c1")])

    ent = fake_graph.get_entity("Auth Service")  # lookup is case-insensitive
    assert ent["type"] == "Service" and "c1" in ent["chunk_ids"]

    nb = fake_graph.neighbors("auth service")
    names = {(n["entity"]["normalized_name"], n["relation_type"], n["direction"])
             for n in nb["neighbors"]}
    assert ("user db", "depends_on", "out") == next(iter(names))


def test_fake_graph_delete_for_chunks_removes_nodes_and_edges(fake_graph):
    fake_graph.upsert_entities([Entity("a", "A", "Concept", "c1")])
    fake_graph.upsert_edges([Edge("a", "b", "uses", "c1")])
    fake_graph.delete_for_chunks(["c1"])
    assert fake_graph.get_entity("a") is None
    assert fake_graph.neighbors("a")["neighbors"] == []


def test_fake_graph_get_missing_entity_returns_none(fake_graph):
    assert fake_graph.get_entity("nope") is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_graph_store_fake.py -v`
Expected: FAIL — `fixture 'fake_graph' not found`.

- [ ] **Step 5: Implement `graph/store.py`**

```python
# src/opendomainmcp/graph/store.py
"""Graph persistence. ``MariaGraphStore`` is the production backend (MariaDB via
PyMySQL); ``NullGraphStore`` is a no-op used where the graph is not wired."""

from __future__ import annotations

from typing import Iterable, Optional, Protocol

from .models import Edge, Entity


class GraphStoreProtocol(Protocol):
    def ensure_schema(self) -> None: ...
    def upsert_entities(self, entities: list[Entity]) -> None: ...
    def upsert_edges(self, edges: list[Edge]) -> None: ...
    def delete_for_chunks(self, chunk_ids: Iterable[str]) -> None: ...
    def get_entity(self, name: str) -> Optional[dict]: ...
    def neighbors(self, name: str, relation_type: Optional[str] = None,
                  depth: int = 1) -> dict: ...


class NullGraphStore:
    """No-op store (graph disabled / direct Pipeline construction in tests)."""

    def ensure_schema(self) -> None: ...
    def upsert_entities(self, entities: list[Entity]) -> None: ...
    def upsert_edges(self, edges: list[Edge]) -> None: ...
    def delete_for_chunks(self, chunk_ids: Iterable[str]) -> None: ...
    def get_entity(self, name: str) -> Optional[dict]:
        return None
    def neighbors(self, name: str, relation_type: Optional[str] = None,
                  depth: int = 1) -> dict:
        return {"entity": None, "neighbors": []}


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS entities (
        normalized_name VARCHAR(255) PRIMARY KEY,
        display_name    VARCHAR(512) NOT NULL,
        type            VARCHAR(64)  NOT NULL,
        confidence      FLOAT        NOT NULL DEFAULT 1.0
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_chunks (
        normalized_name VARCHAR(255) NOT NULL,
        chunk_id        VARCHAR(128) NOT NULL,
        PRIMARY KEY (normalized_name, chunk_id)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS edges (
        src           VARCHAR(255) NOT NULL,
        dst           VARCHAR(255) NOT NULL,
        relation_type VARCHAR(64)  NOT NULL,
        chunk_id      VARCHAR(128) NOT NULL,
        confidence    FLOAT        NOT NULL DEFAULT 1.0,
        PRIMARY KEY (src, dst, relation_type, chunk_id)
    ) CHARACTER SET utf8mb4
    """,
)


class MariaGraphStore:
    """MariaDB-backed graph store. Connections are short-lived per operation to
    stay safe under FastAPI's threaded request handling."""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        import pymysql

        self._pymysql = pymysql
        self._conn_kwargs = dict(host=host, port=port, user=user,
                                 password=password, database=database,
                                 charset="utf8mb4", autocommit=True,
                                 cursorclass=pymysql.cursors.DictCursor)

    def _connect(self):
        # Fail loud: a clear error if MariaDB is unreachable.
        return self._pymysql.connect(**self._conn_kwargs)

    def ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            for ddl in _SCHEMA:
                cur.execute(ddl)

    def upsert_entities(self, entities: list[Entity]) -> None:
        if not entities:
            return
        with self._connect() as conn, conn.cursor() as cur:
            for e in entities:
                cur.execute(
                    "INSERT INTO entities (normalized_name, display_name, type, confidence) "
                    "VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
                    "display_name=VALUES(display_name), type=VALUES(type), "
                    "confidence=GREATEST(confidence, VALUES(confidence))",
                    (e.normalized_name, e.display_name, e.type, e.confidence))
                cur.execute(
                    "INSERT IGNORE INTO entity_chunks (normalized_name, chunk_id) "
                    "VALUES (%s, %s)", (e.normalized_name, e.chunk_id))

    def upsert_edges(self, edges: list[Edge]) -> None:
        if not edges:
            return
        with self._connect() as conn, conn.cursor() as cur:
            for e in edges:
                cur.execute(
                    "INSERT INTO edges (src, dst, relation_type, chunk_id, confidence) "
                    "VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
                    "confidence=GREATEST(confidence, VALUES(confidence))",
                    (e.src, e.dst, e.relation_type, e.chunk_id, e.confidence))

    def delete_for_chunks(self, chunk_ids: Iterable[str]) -> None:
        ids = list(chunk_ids)
        if not ids:
            return
        placeholders = ", ".join(["%s"] * len(ids))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"DELETE FROM edges WHERE chunk_id IN ({placeholders})", ids)
            cur.execute(
                f"DELETE FROM entity_chunks WHERE chunk_id IN ({placeholders})", ids)
            # Drop entities no longer referenced by any chunk.
            cur.execute(
                "DELETE FROM entities WHERE normalized_name NOT IN "
                "(SELECT normalized_name FROM entity_chunks)")

    def get_entity(self, name: str) -> Optional[dict]:
        from .normalize import normalize_name
        norm = normalize_name(name)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT normalized_name, display_name, type, confidence "
                        "FROM entities WHERE normalized_name=%s", (norm,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("SELECT chunk_id FROM entity_chunks WHERE normalized_name=%s", (norm,))
            chunk_ids = [r["chunk_id"] for r in cur.fetchall()]
        return {"name": row["display_name"], "normalized_name": row["normalized_name"],
                "type": row["type"], "confidence": row["confidence"],
                "aliases": [], "chunk_ids": chunk_ids}

    def neighbors(self, name: str, relation_type: Optional[str] = None,
                  depth: int = 1) -> dict:
        from .normalize import normalize_name
        depth = max(1, min(2, depth))  # clamp per Global Constraints
        root = self.get_entity(name)
        if root is None:
            return {"entity": None, "neighbors": []}
        seen = {root["normalized_name"]}
        frontier = [root["normalized_name"]]
        collected: list[dict] = []
        with self._connect() as conn, conn.cursor() as cur:
            for _ in range(depth):
                next_frontier = []
                for norm in frontier:
                    for direction, col, other in (("out", "src", "dst"), ("in", "dst", "src")):
                        sql = (f"SELECT {other} AS other, relation_type FROM edges "
                               f"WHERE {col}=%s")
                        params = [norm]
                        if relation_type:
                            sql += " AND relation_type=%s"
                            params.append(relation_type)
                        cur.execute(sql, params)
                        for r in cur.fetchall():
                            if r["other"] in seen:
                                continue
                            seen.add(r["other"])
                            next_frontier.append(r["other"])
                            ent = self.get_entity(r["other"])
                            if ent:
                                collected.append({"entity": ent,
                                                  "relation_type": r["relation_type"],
                                                  "direction": direction})
                frontier = next_frontier
        return {"entity": root, "neighbors": collected}
```

- [ ] **Step 6: Add `FakeGraphStore` + fixture to conftest**

`tests/conftest.py` 結尾新增（與 `FakeGraphStore` 行為須與 `MariaGraphStore` 對齊）：

```python
class FakeGraphStore:
    """In-memory GraphStoreProtocol implementation for offline tests."""

    def __init__(self):
        self.entities = {}                 # normalized_name -> dict
        self.entity_chunks = {}            # normalized_name -> set(chunk_id)
        self.edges = []                    # list of Edge

    def ensure_schema(self):
        pass

    def upsert_entities(self, entities):
        for e in entities:
            cur = self.entities.get(e.normalized_name)
            conf = max(e.confidence, cur["confidence"]) if cur else e.confidence
            self.entities[e.normalized_name] = {
                "name": e.display_name, "normalized_name": e.normalized_name,
                "type": e.type, "confidence": conf}
            self.entity_chunks.setdefault(e.normalized_name, set()).add(e.chunk_id)

    def upsert_edges(self, edges):
        self.edges.extend(edges)

    def delete_for_chunks(self, chunk_ids):
        ids = set(chunk_ids)
        self.edges = [e for e in self.edges if e.chunk_id not in ids]
        for norm in list(self.entity_chunks):
            self.entity_chunks[norm] -= ids
            if not self.entity_chunks[norm]:
                del self.entity_chunks[norm]
                self.entities.pop(norm, None)

    def get_entity(self, name):
        from opendomainmcp.graph.normalize import normalize_name
        norm = normalize_name(name)
        row = self.entities.get(norm)
        if row is None:
            return None
        return {**row, "aliases": [], "chunk_ids": sorted(self.entity_chunks.get(norm, set()))}

    def neighbors(self, name, relation_type=None, depth=1):
        from opendomainmcp.graph.normalize import normalize_name
        depth = max(1, min(2, depth))
        root = self.get_entity(name)
        if root is None:
            return {"entity": None, "neighbors": []}
        seen = {root["normalized_name"]}
        frontier = [root["normalized_name"]]
        collected = []
        for _ in range(depth):
            nxt = []
            for norm in frontier:
                for e in self.edges:
                    if relation_type and e.relation_type != relation_type:
                        continue
                    if e.src == norm:
                        other, direction = e.dst, "out"
                    elif e.dst == norm:
                        other, direction = e.src, "in"
                    else:
                        continue
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.append(other)
                    ent = self.get_entity(other)
                    if ent:
                        collected.append({"entity": ent, "relation_type": e.relation_type,
                                          "direction": direction})
            frontier = nxt
        return {"entity": root, "neighbors": collected}


@pytest.fixture
def fake_graph():
    return FakeGraphStore()
```

- [ ] **Step 7: Export from `graph/__init__.py`**

```python
# src/opendomainmcp/graph/__init__.py
"""Knowledge graph: typed entities and relations persisted in MariaDB."""

from .models import Edge, Entity
from .store import GraphStoreProtocol, MariaGraphStore, NullGraphStore

__all__ = ["Entity", "Edge", "GraphStoreProtocol", "MariaGraphStore", "NullGraphStore"]
```

- [ ] **Step 8: Write the MariaDB integration test (skipped without env)**

```python
# tests/test_graph_store_mariadb.py
import os

import pytest

from opendomainmcp.graph.models import Edge, Entity

pytestmark = pytest.mark.integration


@pytest.fixture
def maria_store():
    if not os.getenv("GRAPH_DB_HOST"):
        pytest.skip("MariaDB integration env not configured (set GRAPH_DB_HOST)")
    from opendomainmcp.graph.store import MariaGraphStore
    store = MariaGraphStore(
        host=os.environ["GRAPH_DB_HOST"], port=int(os.getenv("GRAPH_DB_PORT", "3306")),
        user=os.environ["GRAPH_DB_USER"], password=os.getenv("GRAPH_DB_PASSWORD", ""),
        database=os.environ["GRAPH_DB_NAME"])
    store.ensure_schema()
    store.delete_for_chunks(["it-c1"])  # clean slate for this chunk id
    return store


def test_mariadb_roundtrip(maria_store):
    maria_store.upsert_entities([
        Entity("auth service", "Auth Service", "Service", "it-c1"),
        Entity("user db", "User DB", "Resource", "it-c1")])
    maria_store.upsert_edges([Edge("auth service", "user db", "depends_on", "it-c1")])
    assert maria_store.get_entity("Auth Service")["type"] == "Service"
    nb = maria_store.neighbors("auth service")
    assert any(n["entity"]["normalized_name"] == "user db" for n in nb["neighbors"])
    maria_store.delete_for_chunks(["it-c1"])
    assert maria_store.get_entity("auth service") is None
```

在 `pyproject.toml` 的 `[tool.pytest.ini_options]`（若無則新增）註冊 marker，避免 unknown-marker 警告：

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests requiring a live MariaDB (set GRAPH_DB_* env to run)",
]
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_graph_store_fake.py -v && pytest tests/test_graph_store_mariadb.py -v`
Expected: fake 測試 PASS（3 passed）；MariaDB 測試在無 env 時 **SKIPPED**（有 env 時 PASS）。

- [ ] **Step 10: Commit**

```bash
git add src/opendomainmcp/graph/store.py src/opendomainmcp/graph/__init__.py src/opendomainmcp/config.py pyproject.toml .env.example tests/conftest.py tests/test_graph_store_fake.py tests/test_graph_store_mariadb.py
git commit -m "feat(graph): MariaDB graph store, protocol, null/fake stores, config"
```

---

## Task 5: Pipeline 與 Context 接線（圖隨向量同步）

**Files:**
- Modify: `src/opendomainmcp/ingest/pipeline.py:68-74` (`__init__`), `:186-197` (prune/upsert 區段)
- Modify: `src/opendomainmcp/context.py`
- Modify: `tests/conftest.py:93-99` (`pipeline` fixture 注入 `fake_graph`)
- Test: `tests/test_pipeline_graph_sync.py`

**Interfaces:**
- Consumes: `build_graph`（Task 3）、`GraphStoreProtocol`/`NullGraphStore`（Task 4）、`FakeGraphStore`（Task 4 conftest）。
- Produces: `Pipeline(store, extractor, settings, splitter=None, graph=None)`；`Context.graph: GraphStoreProtocol`；`build_context()` 連線 MariaDB 並 `ensure_schema()`（fail-loud）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_graph_sync.py
from pathlib import Path

from opendomainmcp.config import Settings
from opendomainmcp.ingest.pipeline import Pipeline


def _pipeline(store, fake_extractor, fake_graph):
    return Pipeline(store, fake_extractor, Settings(chunk_size=200, chunk_overlap=20),
                    graph=fake_graph)


def test_ingest_populates_graph(tmp_path, store, fake_extractor, fake_graph):
    f = tmp_path / "a.txt"
    f.write_text("Payments depends on Ledger and integrates with Billing.")
    _pipeline(store, fake_extractor, fake_graph).ingest_path(str(f))
    # FakeExtractor emits one Concept entity named after the first word ("Payments").
    assert fake_graph.get_entity("Payments") is not None


def test_reingest_prunes_stale_graph_nodes(tmp_path, store, fake_extractor, fake_graph):
    f = tmp_path / "a.txt"
    f.write_text("Payments service.")
    p = _pipeline(store, fake_extractor, fake_graph)
    p.ingest_path(str(f))
    assert fake_graph.get_entity("Payments") is not None
    # Rewrite so the chunk id changes; the old chunk's graph rows must be pruned.
    f.write_text("Refunds workflow now.")
    p.ingest_path(str(f))
    assert fake_graph.get_entity("Payments") is None
    assert fake_graph.get_entity("Refunds") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_graph_sync.py -v`
Expected: FAIL — `Pipeline.__init__` 不接受 `graph`（TypeError）。

- [ ] **Step 3: Add `graph` param to `Pipeline.__init__`**

`pipeline.py` 的 `__init__` 改為：

```python
    def __init__(self, store, extractor, settings,
                 splitter: Optional[RecursiveTextSplitter] = None, graph=None):
        from ..graph.store import NullGraphStore

        self._store = store
        self._extractor = extractor
        self._settings = settings
        self._splitter = splitter or RecursiveTextSplitter(
            settings.chunk_size, settings.chunk_overlap
        )
        self._graph = graph or NullGraphStore()
```

- [ ] **Step 4: Sync graph in `_ingest_file`**

在 `_ingest_file` 的 prune 區段與 upsert 之後加入圖同步。把現有：

```python
        new_ids = {c.id for c in chunks}
        stale = self._store.get_ids_for_source(str(path)) - new_ids
        if stale:
            self._store.delete_ids(stale)
            report.chunks_pruned += len(stale)
            self._emit(progress, "prune", str(path), detail=f"{len(stale)} stale")

        self._emit(progress, "embed", str(path))
        stored = self._store.upsert(chunks)
        self._emit(progress, "store", str(path), detail=f"{stored} chunks")
```

改為：

```python
        new_ids = {c.id for c in chunks}
        stale = self._store.get_ids_for_source(str(path)) - new_ids
        if stale:
            self._store.delete_ids(stale)
            self._graph.delete_for_chunks(stale)
            report.chunks_pruned += len(stale)
            self._emit(progress, "prune", str(path), detail=f"{len(stale)} stale")

        self._emit(progress, "embed", str(path))
        stored = self._store.upsert(chunks)
        self._write_graph(chunks)
        self._emit(progress, "store", str(path), detail=f"{stored} chunks")
```

並在 `_ingest_file` 之後新增 helper：

```python
    def _write_graph(self, chunks: list[Chunk]) -> None:
        from ..graph.builder import build_graph

        for chunk in chunks:
            if not (chunk.knowledge and not chunk.knowledge.is_empty()):
                continue
            entities, edges = build_graph(chunk.knowledge, chunk.id)
            self._graph.upsert_entities(entities)
            self._graph.upsert_edges(edges)
```

> 同時須處理 `_sync_deletions`（整檔被刪）：在 `self._store.delete_ids(...)` 取得的 id 集合上也呼叫 `self._graph.delete_for_chunks(...)`。把 `_sync_deletions` 內 `removed = self._store.delete_ids(self._store.get_ids_for_source(source))` 改為先取 ids：
>
> ```python
>                 ids = self._store.get_ids_for_source(source)
>                 removed = self._store.delete_ids(ids)
>                 self._graph.delete_for_chunks(ids)
> ```

- [ ] **Step 5: Update conftest `pipeline` fixture**

`tests/conftest.py` 的 `pipeline` fixture 改為注入 `fake_graph`：

```python
@pytest.fixture
def pipeline(store, fake_extractor, fake_graph):
    from opendomainmcp.config import Settings
    from opendomainmcp.ingest.pipeline import Pipeline

    settings = Settings(chunk_size=200, chunk_overlap=20)
    return Pipeline(store, fake_extractor, settings, graph=fake_graph)
```

- [ ] **Step 6: Wire `build_context` (fail-loud)**

`context.py` 改為：

```python
from .config import Settings, get_settings
from .embedding import get_embedder
from .extract import get_extractor
from .graph.store import MariaGraphStore
from .ingest.pipeline import Pipeline
from .retrieval import get_reranker
from .store import ChromaStore


@dataclass
class Context:
    settings: Settings
    store: ChromaStore
    pipeline: Pipeline
    graph: MariaGraphStore


def build_context(settings: Settings | None = None, collection: str | None = None) -> Context:
    settings = settings or get_settings()
    embedder = get_embedder(settings)
    store = ChromaStore(
        embedder,
        data_dir=settings.data_dir / "chroma",
        collection_name=collection or settings.collection_name,
        max_retries=settings.max_retries,
        reranker=get_reranker(settings),
    )
    extractor = get_extractor(settings)
    graph = MariaGraphStore(
        host=settings.graph_db_host, port=settings.graph_db_port,
        user=settings.graph_db_user, password=settings.graph_db_password,
        database=settings.graph_db_name,
    )
    # Fail loud: required platform dependency. A clear error beats a late failure
    # deep inside ingestion.
    try:
        graph.ensure_schema()
    except Exception as exc:  # noqa: BLE001 - surface the real cause
        raise RuntimeError(
            f"Cannot connect to MariaDB graph store at "
            f"{settings.graph_db_host}:{settings.graph_db_port}: {exc}"
        ) from exc
    pipeline = Pipeline(store, extractor, settings, graph=graph)
    return Context(settings=settings, store=store, pipeline=pipeline, graph=graph)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_graph_sync.py -v && pytest -q`
Expected: 新測試 PASS；全套件綠燈（既有測試用注入 fake 的 fixture，不碰 MariaDB）。

> 若有任何直接 `build_context()` 的測試此時會嘗試連 MariaDB —— 檢查 `git grep -n "build_context(" tests`，這類測試應已用 `create_app(context=...)` 注入或需標 `integration`。若發現未注入的，於該測試注入既有 fixtures 或標 `@pytest.mark.integration`。

- [ ] **Step 8: Commit**

```bash
git add src/opendomainmcp/ingest/pipeline.py src/opendomainmcp/context.py tests/conftest.py tests/test_pipeline_graph_sync.py
git commit -m "feat(graph): sync entity graph with vectors during ingest + wire build_context"
```

---

## Task 6: 查詢層 — API 端點與 MCP 工具

**Files:**
- Modify: `src/opendomainmcp/api/app.py` (新增 `/api/graph/*` 路由)
- Modify: `src/opendomainmcp/server.py` (新增 graph MCP 工具)
- Test: `tests/test_graph_api.py`、`tests/test_graph_mcp.py`

**Interfaces:**
- Consumes: `Context.graph`（Task 5）、`get_entity`/`neighbors`（Task 4）、`create_app(context=...)`（既有）。
- Produces:
  - `GET /api/graph/entity/{name}` → `{"entity": {...}|None, "neighbors": [...]}`（envelope 沿用既有風格）
  - `GET /api/graph/entities?type=&q=&limit=` → `{"items": [{"name","normalized_name","type"}...]}`
  - MCP 工具 `get_entity(name)`、`list_related_entities(name, relation_type?, depth=1)`

- [ ] **Step 1: Write the failing API test**

```python
# tests/test_graph_api.py
from fastapi.testclient import TestClient

from opendomainmcp.api.app import create_app
from opendomainmcp.config import Settings
from opendomainmcp.context import Context
from opendomainmcp.graph.models import Edge, Entity


def _client(store, fake_graph):
    fake_graph.upsert_entities([
        Entity("auth service", "Auth Service", "Service", "c1"),
        Entity("user db", "User DB", "Resource", "c1")])
    fake_graph.upsert_edges([Edge("auth service", "user db", "depends_on", "c1")])
    ctx = Context(settings=Settings(), store=store, pipeline=None, graph=fake_graph)
    return TestClient(create_app(context=ctx))


def test_get_entity_endpoint_returns_entity_and_neighbors(store, fake_graph):
    resp = _client(store, fake_graph).get("/api/graph/entity/Auth Service")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity"]["type"] == "Service"
    assert body["neighbors"][0]["entity"]["normalized_name"] == "user db"


def test_get_entity_endpoint_404_for_missing(store, fake_graph):
    resp = _client(store, fake_graph).get("/api/graph/entity/nope")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_api.py -v`
Expected: FAIL — 404/route 不存在（或 `Context` 不接受 `graph`，但 Task 5 已加）。

- [ ] **Step 3: Add API routes**

`api/app.py` 在 `create_app` 內、與其他 `@app.get` 同層，新增（緊接 `/api/views` 區段之後即可）：

```python
    @app.get("/api/graph/entity/{name}")
    def graph_entity(name: str):
        result = context.graph.neighbors(name)
        if result["entity"] is None:
            return JSONResponse(status_code=404,
                                content={"error": f"entity not found: {name}"})
        return result

    @app.get("/api/graph/entities")
    def graph_entities(type: str | None = None, q: str | None = None, limit: int = 50):
        # Minimal listing for the future graph UI; backed by get_entity-style rows.
        # Delegates filtering to the store-agnostic helper on the graph store.
        return {"items": context.graph.list_entities(type=type, q=q, limit=limit)}
```

> `list_entities` 是新方法 —— 加到 `GraphStoreProtocol`、`MariaGraphStore`、`NullGraphStore`、`FakeGraphStore`。

`graph/store.py` `GraphStoreProtocol` 新增：

```python
    def list_entities(self, type: Optional[str] = None, q: Optional[str] = None,
                      limit: int = 50) -> list[dict]: ...
```

`MariaGraphStore` 新增：

```python
    def list_entities(self, type=None, q=None, limit=50):
        clauses, params = [], []
        if type:
            clauses.append("type=%s"); params.append(type)
        if q:
            clauses.append("normalized_name LIKE %s")
            params.append(f"%{q.lower().strip()}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(500, limit)))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT normalized_name, display_name, type FROM entities"
                        f"{where} ORDER BY normalized_name LIMIT %s", params)
            return [{"name": r["display_name"], "normalized_name": r["normalized_name"],
                     "type": r["type"]} for r in cur.fetchall()]
```

`NullGraphStore` 新增：

```python
    def list_entities(self, type=None, q=None, limit=50):
        return []
```

`FakeGraphStore`（conftest）新增：

```python
    def list_entities(self, type=None, q=None, limit=50):
        rows = []
        for norm, row in sorted(self.entities.items()):
            if type and row["type"] != type:
                continue
            if q and q.lower().strip() not in norm:
                continue
            rows.append({"name": row["name"], "normalized_name": norm, "type": row["type"]})
        return rows[:max(1, min(500, limit))]
```

- [ ] **Step 4: Run API tests to verify they pass**

Run: `pytest tests/test_graph_api.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the failing MCP test**

```python
# tests/test_graph_mcp.py
from opendomainmcp.config import Settings
from opendomainmcp.context import Context
from opendomainmcp.graph.models import Edge, Entity
from opendomainmcp.server import graph_tool_handlers


def _ctx(store, fake_graph):
    fake_graph.upsert_entities([
        Entity("auth service", "Auth Service", "Service", "c1"),
        Entity("user db", "User DB", "Resource", "c1")])
    fake_graph.upsert_edges([Edge("auth service", "user db", "depends_on", "c1")])
    return Context(settings=Settings(), store=store, pipeline=None, graph=fake_graph)


def test_get_entity_tool(store, fake_graph):
    handlers = graph_tool_handlers(_ctx(store, fake_graph))
    out = handlers["get_entity"](name="Auth Service")
    assert out["entity"]["type"] == "Service"


def test_list_related_entities_tool_clamps_depth(store, fake_graph):
    handlers = graph_tool_handlers(_ctx(store, fake_graph))
    out = handlers["list_related_entities"](name="auth service", depth=5)
    assert out["neighbors"][0]["entity"]["normalized_name"] == "user db"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_graph_mcp.py -v`
Expected: FAIL — `ImportError: graph_tool_handlers`.

- [ ] **Step 7: Add MCP graph tools in `server.py`**

在 `server.py` 新增一個建構 graph 工具處理器的函式（與既有 view server 接線並存；純讀、直接打 `ctx.graph`）：

```python
def graph_tool_handlers(ctx):
    """Return name -> callable for the graph MCP tools. Pure reads over the
    graph store; no retrieval / LLM."""

    def get_entity(name: str):
        return ctx.graph.neighbors(name)

    def list_related_entities(name: str, relation_type: str | None = None, depth: int = 1):
        return ctx.graph.neighbors(name, relation_type=relation_type, depth=depth)

    return {"get_entity": get_entity, "list_related_entities": list_related_entities}
```

> 接線到實際 MCP server：在 `build_view_server`/`get_server` 註冊 Developer 與 Architecture 視圖時，把這兩個工具一併 `@server.tool()` 註冊，body 直接呼叫 `graph_tool_handlers(ctx)[...]`。沿用該檔現有工具註冊樣式（與 `run_view_tool` 工具相同的註冊迴圈），確保 `depth` 由 `neighbors` 內部 clamp 到 1–2。

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_graph_mcp.py -v && pytest -q`
Expected: 全部 PASS；全套件綠燈。

- [ ] **Step 9: Run the full suite + lint check**

Run: `pytest -q`
Expected: 0 failed（既有 133 + 本計畫新增測試全綠；MariaDB 整合測試在無 env 時 skipped）。

- [ ] **Step 10: Commit**

```bash
git add src/opendomainmcp/api/app.py src/opendomainmcp/server.py src/opendomainmcp/graph/store.py tests/conftest.py tests/test_graph_api.py tests/test_graph_mcp.py
git commit -m "feat(graph): entity query API endpoints and MCP tools"
```

---

## Task 7: 多知識庫（collection）隔離

> Added after the final whole-branch review surfaced that the graph was platform-global while Chroma is per-collection. The user chose per-collection isolation.

**Files:**
- Modify: `src/opendomainmcp/graph/store.py` (schema + all methods + `delete_collection`)
- Modify: `src/opendomainmcp/context.py` (pass collection into `MariaGraphStore`)
- Modify: `src/opendomainmcp/api/app.py` (`delete_collection` endpoint prunes graph)
- Modify: `tests/conftest.py` (`FakeGraphStore` collection-aware)
- Modify: `tests/test_graph_store_mariadb.py` (cross-collection isolation + delete_collection)
- Test: `tests/test_graph_collection_scope.py` (offline isolation via shared-backing fakes)

**Interfaces:**
- Consumes: existing `GraphStoreProtocol`, `MariaGraphStore`, `FakeGraphStore`, `build_context`.
- Produces:
  - `MariaGraphStore(host, port, user, password, database, collection)` — bound to a collection; every read/write/delete is scoped by it.
  - `GraphStoreProtocol.delete_collection(name: str) -> None` (added to all stores).
  - `FakeGraphStore(collection="domain_knowledge", backing=None)` — `backing` is an optional shared dict-of-dicts so two instances bound to different collections can share one underlying store and prove filter-based isolation offline.

- [ ] **Step 1: Write the failing offline isolation test**

```python
# tests/test_graph_collection_scope.py
from opendomainmcp.graph.models import Entity
from tests.conftest import FakeGraphStore


def test_collection_isolation_via_shared_backing():
    backing = {}
    a = FakeGraphStore(collection="a", backing=backing)
    b = FakeGraphStore(collection="b", backing=backing)
    a.upsert_entities([Entity("auth", "Auth", "Service", "c1")])
    assert a.get_entity("auth") is not None
    assert b.get_entity("auth") is None          # isolated by collection
    assert b.list_entities() == []


def test_delete_collection_removes_only_that_collection():
    backing = {}
    a = FakeGraphStore(collection="a", backing=backing)
    b = FakeGraphStore(collection="b", backing=backing)
    a.upsert_entities([Entity("x", "X", "Concept", "c1")])
    b.upsert_entities([Entity("y", "Y", "Concept", "c2")])
    a.delete_collection("a")
    assert a.get_entity("x") is None
    assert b.get_entity("y") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `source .venv/bin/activate && ODM_EXTRACT_KNOWLEDGE=true python -m pytest tests/test_graph_collection_scope.py -v`
Expected: FAIL — `FakeGraphStore` does not accept `collection`/`backing`.

- [ ] **Step 3: Make `MariaGraphStore` collection-scoped**

In `graph/store.py`:
- Add `collection VARCHAR(255) NOT NULL` to all three `CREATE TABLE` statements and incorporate it into each PRIMARY KEY: `entities (collection, normalized_name)`, `entity_chunks (collection, normalized_name, chunk_id)`, `edges (collection, src, dst, relation_type, chunk_id)`.
- `__init__` gains a `collection: str` parameter stored as `self._collection`.
- Every `INSERT`/`SELECT`/`DELETE` includes `collection` (insert the value; filter `WHERE collection=%s AND ...`). The orphan-entity cleanup in `delete_for_chunks` becomes `DELETE FROM entities WHERE collection=%s AND normalized_name NOT IN (SELECT normalized_name FROM entity_chunks WHERE collection=%s)`.
- Add `delete_collection(self, name: str)`: delete all rows from the three tables `WHERE collection=%s` (name), so the API can prune an arbitrary named collection regardless of the bound one.

> Read the current `store.py` carefully and thread `self._collection` through every existing statement — do not miss `get_entity`'s `entity_chunks` lookup or the `_get_entity_with_cur` helper.

- [ ] **Step 4: Make `FakeGraphStore` collection-aware (conftest)**

Refactor `FakeGraphStore` so its state lives in a `backing` dict keyed by collection (default a fresh dict), accepts `collection` + optional shared `backing`, and filters every operation by `self._collection`. Add `delete_collection(name)` that clears only `name`'s slice of `backing`. Keep all return shapes identical to before. The existing `fake_graph` fixture stays `FakeGraphStore()` (default collection) — confirm existing tests still pass.

- [ ] **Step 5: Run isolation tests + full suite**

Run: `source .venv/bin/activate && ODM_EXTRACT_KNOWLEDGE=true python -m pytest tests/test_graph_collection_scope.py -v && ODM_EXTRACT_KNOWLEDGE=true python -m pytest -q`
Expected: new tests PASS; full suite green.

- [ ] **Step 6: Wire collection through `build_context` and the API drop path**

- `context.py`: construct `MariaGraphStore(..., collection=collection or settings.collection_name)`.
- `api/app.py` `delete_collection`: after `ctx.store.drop_collection(name)`, call `ctx.graph.delete_collection(name)`.

- [ ] **Step 7: Extend the MariaDB integration test**

Add to `tests/test_graph_store_mariadb.py` a test (same `@pytest.mark.integration`, skips without `GRAPH_DB_HOST`) that builds two `MariaGraphStore` on the SAME database with different `collection` values, upserts an entity in each, asserts each store sees only its own, then `delete_collection` on one leaves the other intact.

- [ ] **Step 8: Run full suite + commit**

Run: `source .venv/bin/activate && ODM_EXTRACT_KNOWLEDGE=true python -m pytest -q` → green (1 skipped).

```bash
git add -A
git commit -m "feat(graph): scope entity graph per collection (schema, stores, drop path)"
```

---

## Self-Review

**Spec coverage:**
- spec §4 模組（models/normalize/builder/store）→ Tasks 1,3,4 ✅
- spec §5 萃取疊加 → Task 2 ✅
- spec §6 查詢層（API + MCP，depth 上限 2）→ Task 6（clamp 在 `neighbors`）✅
- spec §7 config + fail-loud + Context 接線 → Tasks 4,5 ✅
- spec §8 測試策略（Protocol + FakeGraphStore + integration marker）→ Tasks 4,5,6 ✅
- spec §10 任務切分 6 項 → Tasks 1–6 ✅
- spec §9 `graph rebuild` CLI 回填 → **次要/可選**，spec 已標明非核心；本計畫**未納入**（YAGNI，待需要時另開 task）。已在此明列以免被當成漏項。

**Placeholder scan:** 無 TBD/TODO/「add error handling」式佔位；所有 code step 皆含完整程式碼。

**Type consistency:**
- `get_entity` 回傳 dict 形狀（`name/normalized_name/type/confidence/aliases/chunk_ids`）在 Maria/Null/Fake 三實作與測試一致。
- `neighbors` 回傳 `{"entity", "neighbors":[{"entity","relation_type","direction"}]}` 一致。
- `Pipeline(..., graph=None)`、`Context(..., graph=...)` 在 Tasks 5/6 與測試一致。
- `list_entities(type, q, limit)` 在 Protocol/Maria/Null/Fake 一致（Task 6 同步加入四處）。
- `build_graph(knowledge, chunk_id)`、`normalize_name(name)` 跨 Task 3/5 一致。

---

## Execution Handoff

見對話中的執行選項提示。
