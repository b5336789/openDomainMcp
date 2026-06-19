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


def test_get_entity_tool_missing_returns_none(store, fake_graph):
    handlers = graph_tool_handlers(_ctx(store, fake_graph))
    out = handlers["get_entity"](name="nonexistent entity")
    assert out["entity"] is None
    assert out["neighbors"] == []


def test_list_related_entities_tool_with_relation_type(store, fake_graph):
    handlers = graph_tool_handlers(_ctx(store, fake_graph))
    out = handlers["list_related_entities"](name="auth service", relation_type="depends_on")
    assert len(out["neighbors"]) == 1
    assert out["neighbors"][0]["relation_type"] == "depends_on"
