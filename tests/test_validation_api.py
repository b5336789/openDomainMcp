from __future__ import annotations

from fastapi.testclient import TestClient

from opendomainmcp.api import validation_routes
from opendomainmcp.api.app import create_app
from opendomainmcp.config import Settings
from opendomainmcp.context import Context
from opendomainmcp.metrics import MetricsRecorder
from opendomainmcp.models import Chunk, KnowledgeUnit


def _client(store, pipeline, fake_graph, tmp_path):
    settings = Settings(data_dir=tmp_path)
    ctx = Context(settings=settings, store=store, pipeline=pipeline, graph=fake_graph)
    app = create_app(context=ctx, context_factory=lambda **_: ctx)
    return TestClient(app), ctx


def _approved_chunk(text="rollback runbook"):
    return Chunk(
        text=text,
        source="runbooks/rollback.md",
        kind="text",
        knowledge=KnowledgeUnit(
            summary=text,
            knowledge_type="Runbook",
            audience=["product_manager"],
            review_status="approved",
        ),
    )


def test_create_and_list_validation_scenarios(store, pipeline, fake_graph, tmp_path):
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    created = client.post(
        "/api/validation/scenarios",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "How do I roll back?",
        },
    ).json()

    assert created["view"] == "product"
    assert created["name"] == "Rollback"
    assert created["query"] == "How do I roll back?"

    listed = client.get("/api/validation/scenarios", params={"view": "product"}).json()
    assert listed == [{**created, "latest_run": None}]
    assert client.get("/api/validation/scenarios", params={"view": "developer"}).json() == []


def test_create_validation_rejects_blank_fields(store, pipeline, fake_graph, tmp_path):
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    resp = client.post(
        "/api/validation/scenarios",
        json={"view": "product", "name": " ", "query": "How do I roll back?"},
    )

    assert resp.status_code == 422
    assert "name is required" in resp.text


def test_create_validation_rejects_unknown_view(store, pipeline, fake_graph, tmp_path):
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    resp = client.post(
        "/api/validation/scenarios",
        json={"view": "missing", "name": "Rollback", "query": "How?"},
    )

    assert resp.status_code == 404
    assert "unknown view" in resp.text


def test_run_validation_scenario_records_passed_run(store, pipeline, fake_graph, tmp_path):
    store.upsert([_approved_chunk()])
    client, _ = _client(store, pipeline, fake_graph, tmp_path)
    scenario = client.post(
        "/api/validation/scenarios",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "rollback",
        },
    ).json()

    run = client.post(f"/api/validation/scenarios/{scenario['id']}/run").json()

    assert run["scenario_id"] == scenario["id"]
    assert run["status"] == "passed"
    assert run["grounding_hits"] > 0
    assert run["tool_results"] > 0

    summary = client.get("/api/validation/summary", params={"view": "product"}).json()
    assert summary["status"] == "passed"
    assert summary["scenario_count"] == 1
    assert summary["passed"] == 1
    assert summary["failed"] == 0

    listed = client.get("/api/validation/scenarios", params={"view": "product"}).json()
    assert listed[0]["latest_run"]["id"] == run["id"]


def test_run_validation_records_failed_when_no_grounding(
    store, pipeline, fake_graph, tmp_path
):
    client, _ = _client(store, pipeline, fake_graph, tmp_path)
    scenario = client.post(
        "/api/validation/scenarios",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "rollback",
        },
    ).json()

    run = client.post(f"/api/validation/scenarios/{scenario['id']}/run").json()

    assert run["status"] == "failed"
    assert run["grounding_hits"] == 0
    assert run["tool_results"] == 0


def test_run_unknown_validation_scenario_returns_404(
    store, pipeline, fake_graph, tmp_path
):
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    resp = client.post("/api/validation/scenarios/nope/run")

    assert resp.status_code == 404


def test_run_and_save_convenience_endpoint(store, pipeline, fake_graph, tmp_path):
    store.upsert([_approved_chunk()])
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    payload = client.post(
        "/api/validation/run",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "rollback",
        },
    ).json()

    assert payload["scenario"]["name"] == "Rollback"
    assert payload["run"]["status"] == "passed"
    assert payload["result"]["view"] == "product"
    assert payload["summary"]["status"] == "passed"


def test_run_and_save_records_failed_run_when_simulator_errors(
    monkeypatch, store, pipeline, fake_graph, tmp_path
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("simulator exploded")

    monkeypatch.setattr(validation_routes, "run_simulation", boom)
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    payload = client.post(
        "/api/validation/run",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "rollback",
        },
    ).json()

    assert payload["scenario"]["name"] == "Rollback"
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error"] == "simulator exploded"
    assert payload["result"] is None
    assert payload["summary"]["status"] == "failed"
    assert payload["summary"]["failed"] == 1


def test_validation_run_records_retrieval_metrics(store, pipeline, fake_graph, tmp_path):
    store.upsert([_approved_chunk()])
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    client.post(
        "/api/validation/run",
        json={
            "view": "product",
            "name": "Rollback",
            "query": "rollback",
        },
    )

    events = MetricsRecorder(tmp_path).read_events()
    assert len(events) == 1
    assert events[0].kind == "search"
    assert events[0].query == "rollback"
    assert events[0].hits > 0


def test_validation_routes_require_api_key_when_auth_enabled(
    monkeypatch, store, pipeline, fake_graph, tmp_path
):
    monkeypatch.setenv("ODM_AUTH_ENABLED", "true")
    monkeypatch.setenv("ODM_API_KEYS", "secret:dev:product")
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    resp = client.get("/api/validation/scenarios", params={"view": "product"})

    assert resp.status_code == 401


def test_validation_run_enforces_view_scope(
    monkeypatch, store, pipeline, fake_graph, tmp_path
):
    monkeypatch.setenv("ODM_AUTH_ENABLED", "true")
    monkeypatch.setenv("ODM_API_KEYS", "secret:dev:product")
    client, _ = _client(store, pipeline, fake_graph, tmp_path)

    resp = client.post(
        "/api/validation/run",
        headers={"X-API-Key": "secret"},
        json={
            "view": "developer",
            "name": "Restricted",
            "query": "search code",
        },
    )

    assert resp.status_code == 403
