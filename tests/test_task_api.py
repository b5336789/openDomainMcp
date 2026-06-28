import time

import pytest
from fastapi.testclient import TestClient

from opendomainmcp.api.app import create_app
from opendomainmcp.config import Settings
from opendomainmcp.context import Context


@pytest.fixture
def client(store, pipeline, fake_graph, tmp_path):
    settings = Settings(data_dir=tmp_path)
    ctx = Context(settings=settings, store=store, pipeline=pipeline, graph=fake_graph)
    app = create_app(context=ctx, context_factory=lambda: ctx)
    return TestClient(app), ctx, tmp_path


def _wait(tc, job_id, statuses, tries=200):
    for _ in range(tries):
        tasks = tc.get("/api/tasks").json()["tasks"]
        t = next((x for x in tasks if x["id"] == job_id), None)
        if t and t["status"] in statuses:
            return t
        time.sleep(0.02)
    raise AssertionError(f"task {job_id} never reached {statuses}")


def _task_store(tc):
    tc.get("/api/tasks")
    return tc.app.state.task_store


def test_create_ingest_task_runs_to_done(client, tmp_path):
    tc, _, _ = client
    src = tmp_path / "corpus"
    src.mkdir()
    (src / "a.py").write_text("def a():\n    return 1\n")
    (src / "b.md").write_text("Beta billing.\n")

    resp = tc.post("/api/tasks", json={"type": "ingest",
                                       "params": {"path": str(src)}})
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    t = _wait(tc, job_id, {"done"})
    assert t["result"]["files_indexed"] == 2

    page = tc.get(f"/api/tasks/{job_id}/children").json()
    assert page["total"] == 2

    res = tc.post("/api/search", json={"query": "billing"}).json()
    assert isinstance(res, list)


def test_unknown_type_is_400(client):
    tc, _, _ = client
    assert tc.post("/api/tasks", json={"type": "nope", "params": {}}).status_code == 400


def test_children_unknown_id_404(client):
    tc, _, _ = client
    assert tc.get("/api/tasks/zzz/children").status_code == 404


def test_cancel_unknown_id_404(client):
    tc, _, _ = client
    assert tc.delete("/api/tasks/does-not-exist").status_code == 404


def test_clear_finished(client, tmp_path):
    tc, _, _ = client
    src = tmp_path / "c2"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    job_id = tc.post("/api/tasks", json={"type": "ingest",
                                         "params": {"path": str(src)}}).json()["id"]
    _wait(tc, job_id, {"done"})
    cleared = tc.post("/api/tasks/clear").json()["cleared"]
    assert cleared >= 1


def test_retry_error_task_returns_new_queued_task(client):
    tc, ctx, _ = client
    store = _task_store(tc)
    original = store.create("ingest", "Ingest failed", ctx.store.stats()["collection"], {"path": "/missing"})
    store.transition(
        original.id,
        "error",
        error="FileNotFoundError('missing')",
        error_type="FileNotFoundError",
        error_message="missing",
    )

    resp = tc.post(f"/api/tasks/{original.id}/retry")

    assert resp.status_code == 200
    retry = resp.json()
    assert retry["id"] != original.id
    assert retry["status"] == "queued"
    assert retry["type"] == "ingest"
    assert retry["title"] == "Ingest failed"
    assert retry["params"] == {"path": "/missing"}
    assert retry["result"]["retry_of"] == original.id


def test_retry_unknown_task_is_404(client):
    tc, _, _ = client

    resp = tc.post("/api/tasks/does-not-exist/retry")

    assert resp.status_code == 404


def test_retry_non_retryable_task_is_409(client):
    tc, ctx, _ = client
    store = _task_store(tc)
    queued = store.create("ingest", "Queued", ctx.store.stats()["collection"], {"path": "/src"})

    resp = tc.post(f"/api/tasks/{queued.id}/retry")

    assert resp.status_code == 409
