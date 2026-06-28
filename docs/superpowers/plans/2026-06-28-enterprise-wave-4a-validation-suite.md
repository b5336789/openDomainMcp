# Enterprise Wave 4A Validation Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent validation scenario suite so Simulator runs can become reusable pass/fail evidence for Quality Lab and MCP Publish.

**Architecture:** Validation lives in a focused backend domain module with file-backed persistence under the active data directory. A new validation API reuses the existing simulator execution behavior, records scenario runs, and exposes collection/view summaries. Quality Evidence consumes the summary as a Simulation gate; the frontend adds scenario controls in Simulator and compact validation summaries in MCP Publish.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, React, TypeScript, Vite, Playwright.

---

## File Map

- Create `src/opendomainmcp/validation/__init__.py`: exports validation store, builders, summary helpers, and pass/fail constants.
- Create `src/opendomainmcp/validation/store.py`: owns `validation_runs.json`, atomic persistence, scenario/run listing, and summaries.
- Create `src/opendomainmcp/api/simulation.py`: shared simulator executor used by `/api/simulate` and validation routes.
- Create `src/opendomainmcp/api/validation_routes.py`: HTTP API for scenarios, runs, and summaries.
- Modify `src/opendomainmcp/api/app.py`: use shared simulator executor and include validation router.
- Modify `src/opendomainmcp/quality/evidence.py`: add Simulation gate from validation summary.
- Modify `src/opendomainmcp/api/mcp_endpoints.py`: enrich endpoint rows with validation summary.
- Create `tests/test_validation_store.py`: unit coverage for persistence, filtering, pass/fail, and corrupt file behavior.
- Create `tests/test_validation_api.py`: API coverage for create/list/run/summary and error cases.
- Modify `tests/test_quality_evidence.py`: include Simulation gate cases.
- Modify `tests/test_mcp_endpoints.py`: endpoint rows include validation summaries.
- Modify `tests/test_integration_wiring.py`: real app exposes validation routes.
- Modify `web/src/api.ts`: add validation types and client methods.
- Modify `web/src/pages/Simulator.tsx`: list saved scenarios, save current result, run saved scenario.
- Modify `web/src/pages/McpBuilder.tsx`: render endpoint validation summary.
- Modify `web/tests/helpers/mockApi.ts`: add default validation payloads and Simulation evidence gate.
- Modify `web/tests/simulator.spec.ts`: verify scenario save/run UI.
- Modify `web/tests/quality_lab.spec.ts`: expect Simulation gate.
- Modify `web/tests/mcp_builder.spec.ts`: expect endpoint validation summary.
- Modify `docs/DEVLOG.md`, `docs/TASKS.md`: record Wave 4A completion.

## Task 1: Validation Store Domain

**Files:**
- Create: `src/opendomainmcp/validation/__init__.py`
- Create: `src/opendomainmcp/validation/store.py`
- Test: `tests/test_validation_store.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/test_validation_store.py`:

```python
from __future__ import annotations

import json

import pytest

from opendomainmcp.validation import (
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    ValidationStore,
    build_run,
    build_scenario,
    summarize_validation,
)


def _result(hits=2, tool_results=2):
    return {
        "view": "product",
        "grounding": {
            "hits": hits,
            "avg_score": 0.75,
            "knowledge_types": ["Runbook"],
        },
        "tools": [
            {
                "tool": "search_features",
                "results": [
                    {
                        "id": "chunk-1",
                        "text": "rollback steps",
                        "score": 0.75,
                        "metadata": {"knowledge_type": "Runbook"},
                    }
                ][:tool_results],
            }
        ],
    }


def test_scenarios_persist_and_filter_by_collection_and_view(tmp_path):
    store = ValidationStore(tmp_path)
    alpha = store.append_scenario(
        build_scenario(
            collection="alpha",
            view="product",
            name="Rollback",
            query="How do I roll back?",
        )
    )
    store.append_scenario(
        build_scenario(
            collection="alpha",
            view="operations",
            name="Deploy",
            query="How do I deploy?",
        )
    )
    store.append_scenario(
        build_scenario(
            collection="beta",
            view="product",
            name="Billing",
            query="How do I bill?",
        )
    )

    reloaded = ValidationStore(tmp_path)

    assert reloaded.scenarios("alpha", "product") == [alpha]
    assert [s["name"] for s in reloaded.scenarios("alpha")] == ["Rollback", "Deploy"]


def test_run_builder_marks_passed_when_grounded_with_tool_results():
    scenario = build_scenario(
        collection="alpha",
        view="product",
        name="Rollback",
        query="How do I roll back?",
    )

    run = build_run(collection="alpha", scenario=scenario, result=_result())

    assert run["status"] == VALIDATION_PASSED
    assert run["grounding_hits"] == 2
    assert run["avg_score"] == 0.75
    assert run["tool_results"] == 1
    assert run["knowledge_types"] == ["Runbook"]
    assert run["error"] == ""


def test_run_builder_marks_failed_without_grounding_or_tool_results():
    scenario = build_scenario(
        collection="alpha",
        view="product",
        name="Rollback",
        query="How do I roll back?",
    )

    no_grounding = build_run(collection="alpha", scenario=scenario, result=_result(hits=0))
    no_results = build_run(collection="alpha", scenario=scenario, result=_result(tool_results=0))

    assert no_grounding["status"] == VALIDATION_FAILED
    assert no_results["status"] == VALIDATION_FAILED


def test_failed_run_can_record_error():
    scenario = build_scenario(
        collection="alpha",
        view="product",
        name="Rollback",
        query="How do I roll back?",
    )

    run = build_run(collection="alpha", scenario=scenario, error="simulator exploded")

    assert run["status"] == VALIDATION_FAILED
    assert run["grounding_hits"] == 0
    assert run["tool_results"] == 0
    assert run["error"] == "simulator exploded"


def test_summary_uses_latest_run_per_scenario(tmp_path):
    store = ValidationStore(tmp_path)
    scenario = store.append_scenario(
        build_scenario(
            collection="alpha",
            view="product",
            name="Rollback",
            query="How do I roll back?",
        )
    )
    first = build_run(collection="alpha", scenario=scenario, result=_result(hits=0))
    first["created_at"] = 1
    latest = build_run(collection="alpha", scenario=scenario, result=_result(hits=2))
    latest["created_at"] = 2
    store.append_run(first)
    store.append_run(latest)

    summary = summarize_validation(store, "alpha", "product")

    assert summary["status"] == VALIDATION_PASSED
    assert summary["scenario_count"] == 1
    assert summary["latest_run_count"] == 1
    assert summary["passed"] == 1
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 1.0
    assert summary["latest_run"]["id"] == latest["id"]


def test_summary_is_validating_when_no_runs(tmp_path):
    store = ValidationStore(tmp_path)
    store.append_scenario(
        build_scenario(
            collection="alpha",
            view="product",
            name="Rollback",
            query="How do I roll back?",
        )
    )

    summary = summarize_validation(store, "alpha", "product")

    assert summary["status"] == "validating"
    assert summary["scenario_count"] == 1
    assert summary["latest_run_count"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 0.0


def test_corrupt_validation_file_fails_loudly(tmp_path):
    path = tmp_path / "validation_runs.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt validation file"):
        ValidationStore(tmp_path)


def test_validation_file_requires_object(tmp_path):
    path = tmp_path / "validation_runs.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain an object"):
        ValidationStore(tmp_path)
```

- [ ] **Step 2: Run store tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_validation_store.py -q
```

Expected: fail during collection with `ModuleNotFoundError: No module named 'opendomainmcp.validation'`.

- [ ] **Step 3: Implement validation store**

Create `src/opendomainmcp/validation/store.py`:

```python
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

VALIDATION_PASSED = "passed"
VALIDATION_FAILED = "failed"
VALIDATION_VALIDATING = "validating"


def build_scenario(*, collection: str, view: str, name: str, query: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "collection": collection,
        "view": view,
        "name": name.strip(),
        "query": query.strip(),
        "created_at": time.time(),
    }


def _tool_result_count(result: dict) -> int:
    return sum(len(tool.get("results") or []) for tool in result.get("tools", []))


def build_run(
    *,
    collection: str,
    scenario: dict,
    result: dict | None = None,
    error: str = "",
) -> dict:
    result = result or {}
    grounding = result.get("grounding") or {}
    hits = int(grounding.get("hits") or 0)
    tool_results = _tool_result_count(result)
    status = (
        VALIDATION_PASSED
        if hits > 0 and tool_results > 0 and not error
        else VALIDATION_FAILED
    )
    return {
        "id": uuid.uuid4().hex,
        "scenario_id": scenario["id"],
        "collection": collection,
        "view": scenario["view"],
        "query": scenario["query"],
        "status": status,
        "grounding_hits": hits,
        "avg_score": float(grounding.get("avg_score") or 0.0),
        "tool_results": tool_results,
        "knowledge_types": list(grounding.get("knowledge_types") or []),
        "error": error,
        "created_at": time.time(),
    }


class ValidationStore:
    FILENAME = "validation_runs.json"

    def __init__(self, data_dir):
        self._path = Path(data_dir) / self.FILENAME
        self._data = self._load()

    def _load(self) -> dict[str, list[dict]]:
        if not self._path.exists():
            return {"scenarios": [], "runs": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt validation file {self._path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Validation file {self._path} must contain an object.")
        return {
            "scenarios": list(data.get("scenarios", [])),
            "runs": list(data.get("runs", [])),
        }

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        os.replace(tmp, self._path)

    def append_scenario(self, scenario: dict) -> dict:
        self._data["scenarios"].append(scenario)
        self._persist()
        return scenario

    def append_run(self, run: dict) -> dict:
        self._data["runs"].append(run)
        self._persist()
        return run

    def scenarios(self, collection: str, view: str | None = None) -> list[dict]:
        return [
            s
            for s in self._data["scenarios"]
            if s.get("collection") == collection and (view is None or s.get("view") == view)
        ]

    def scenario(self, collection: str, scenario_id: str) -> dict | None:
        for scenario in self._data["scenarios"]:
            if scenario.get("collection") == collection and scenario.get("id") == scenario_id:
                return scenario
        return None

    def runs(
        self,
        collection: str,
        view: str | None = None,
        scenario_id: str | None = None,
    ) -> list[dict]:
        items = [
            r
            for r in self._data["runs"]
            if r.get("collection") == collection
            and (view is None or r.get("view") == view)
            and (scenario_id is None or r.get("scenario_id") == scenario_id)
        ]
        return sorted(items, key=lambda r: r.get("created_at", 0), reverse=True)


def summarize_validation(
    store: ValidationStore,
    collection: str,
    view: str | None = None,
) -> dict:
    scenarios = store.scenarios(collection, view)
    latest_runs: list[dict] = []
    for scenario in scenarios:
        runs = store.runs(collection, view=scenario["view"], scenario_id=scenario["id"])
        if runs:
            latest_runs.append(runs[0])
    failed = sum(1 for run in latest_runs if run.get("status") == VALIDATION_FAILED)
    passed = sum(1 for run in latest_runs if run.get("status") == VALIDATION_PASSED)
    latest = sorted(latest_runs, key=lambda r: r.get("created_at", 0), reverse=True)
    if not latest_runs:
        status = VALIDATION_VALIDATING
    elif failed:
        status = VALIDATION_FAILED
    else:
        status = VALIDATION_PASSED
    return {
        "collection": collection,
        "view": view,
        "status": status,
        "scenario_count": len(scenarios),
        "latest_run_count": len(latest_runs),
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / len(latest_runs)) if latest_runs else 0.0,
        "latest_run": latest[0] if latest else None,
    }
```

Create `src/opendomainmcp/validation/__init__.py`:

```python
from .store import (
    VALIDATION_FAILED,
    VALIDATION_PASSED,
    VALIDATION_VALIDATING,
    ValidationStore,
    build_run,
    build_scenario,
    summarize_validation,
)

__all__ = [
    "VALIDATION_FAILED",
    "VALIDATION_PASSED",
    "VALIDATION_VALIDATING",
    "ValidationStore",
    "build_run",
    "build_scenario",
    "summarize_validation",
]
```

- [ ] **Step 4: Run store tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_validation_store.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit validation store**

```bash
git add src/opendomainmcp/validation tests/test_validation_store.py
git commit -m "feat: add validation scenario store"
```

## Task 2: Shared Simulator Executor And Validation API

**Files:**
- Create: `src/opendomainmcp/api/simulation.py`
- Create: `src/opendomainmcp/api/validation_routes.py`
- Modify: `src/opendomainmcp/api/app.py`
- Test: `tests/test_validation_api.py`
- Test: `tests/test_integration_wiring.py`

- [ ] **Step 1: Write failing validation API tests**

Create `tests/test_validation_api.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from opendomainmcp.api.app import create_app
from opendomainmcp.config import Settings
from opendomainmcp.context import Context
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
    assert listed == [created]
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
```

Modify `tests/test_integration_wiring.py` by adding:

```python
def test_validation_routes_wired(client):
    assert client.get("/api/validation/scenarios").status_code == 200
    assert client.get("/api/validation/summary").status_code == 200
```

- [ ] **Step 2: Run validation API tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_validation_api.py tests/test_integration_wiring.py::test_validation_routes_wired -q
```

Expected: fail with `404` for `/api/validation/*` endpoints.

- [ ] **Step 3: Extract simulator executor**

Create `src/opendomainmcp/api/simulation.py`:

```python
from __future__ import annotations

from fastapi import HTTPException

from ..context import Context
from ..views import VIEWS, run_view_tool


def run_simulation(ctx: Context, view: str, query: str, top_k: int = 5) -> dict:
    spec = VIEWS.get(view)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown view {view!r}")

    tools_out, all_results, seen = [], [], set()
    for tool in spec.tools:
        results = run_view_tool(ctx, tool, query, top_k)
        tools_out.append({"tool": tool.name, "results": results})
        for result in results:
            if result["id"] not in seen:
                seen.add(result["id"])
                all_results.append(result)

    scores = [result["score"] for result in all_results]
    types = sorted(
        {
            result["metadata"].get("knowledge_type", "")
            for result in all_results
        }
        - {""}
    )
    grounding = {
        "hits": len(all_results),
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "knowledge_types": types,
    }
    return {"view": view, "tools": tools_out, "grounding": grounding}
```

Modify `/api/simulate` in `src/opendomainmcp/api/app.py` so the handler becomes:

```python
    @app.post("/api/simulate")
    def simulate(req: SimulateRequest, ctx: Context = Depends(get_ctx),
                 principal: dict = Depends(auth_dependency)):
        from .simulation import run_simulation

        require_view_access(principal, req.view)
        result = run_simulation(ctx, req.view, req.query, req.top_k)
        all_results = []
        seen = set()
        for tool in result["tools"]:
            for item in tool["results"]:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    all_results.append(item)
        insight_routes.record_retrieval(ctx, "search", req.query, all_results)
        return result
```

- [ ] **Step 4: Implement validation routes**

Create `src/opendomainmcp/api/validation_routes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..context import Context
from ..validation import (
    ValidationStore,
    build_run,
    build_scenario,
    summarize_validation,
)
from ..views import VIEW_NAMES
from .deps import get_ctx
from .simulation import run_simulation

router = APIRouter()


class ScenarioRequest(BaseModel):
    view: str
    name: str
    query: str


class RunRequest(BaseModel):
    view: str
    query: str
    name: str = ""
    top_k: int = 5


def _collection(ctx: Context) -> str:
    stats = ctx.store.stats()
    return str(stats.get("collection") or ctx.settings.collection_name)


def _validate_view(view: str) -> None:
    if view not in VIEW_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown view {view!r}")


def _validate_required(value: str, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    return stripped


@router.get("/api/validation/scenarios")
def list_scenarios(view: str | None = None, ctx: Context = Depends(get_ctx)) -> list[dict]:
    if view is not None:
        _validate_view(view)
    return ValidationStore(ctx.settings.data_dir).scenarios(_collection(ctx), view)


@router.post("/api/validation/scenarios")
def create_scenario(body: ScenarioRequest, ctx: Context = Depends(get_ctx)) -> dict:
    _validate_view(body.view)
    scenario = build_scenario(
        collection=_collection(ctx),
        view=body.view,
        name=_validate_required(body.name, "name"),
        query=_validate_required(body.query, "query"),
    )
    return ValidationStore(ctx.settings.data_dir).append_scenario(scenario)


@router.post("/api/validation/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, ctx: Context = Depends(get_ctx)) -> dict:
    collection = _collection(ctx)
    store = ValidationStore(ctx.settings.data_dir)
    scenario = store.scenario(collection, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario_id!r}")
    try:
        result = run_simulation(ctx, scenario["view"], scenario["query"])
        run = build_run(collection=collection, scenario=scenario, result=result)
    except Exception as exc:
        run = build_run(collection=collection, scenario=scenario, error=str(exc))
    return store.append_run(run)


@router.post("/api/validation/run")
def run_validation(body: RunRequest, ctx: Context = Depends(get_ctx)) -> dict:
    _validate_view(body.view)
    collection = _collection(ctx)
    store = ValidationStore(ctx.settings.data_dir)
    scenario = build_scenario(
        collection=collection,
        view=body.view,
        name=_validate_required(body.name or body.query, "name"),
        query=_validate_required(body.query, "query"),
    )
    scenario = store.append_scenario(scenario)
    result = run_simulation(ctx, body.view, scenario["query"], body.top_k)
    run = store.append_run(
        build_run(collection=collection, scenario=scenario, result=result)
    )
    return {
        "scenario": scenario,
        "run": run,
        "result": result,
        "summary": summarize_validation(store, collection, body.view),
    }


@router.get("/api/validation/summary")
def validation_summary(view: str | None = None, ctx: Context = Depends(get_ctx)) -> dict:
    if view is not None:
        _validate_view(view)
    store = ValidationStore(ctx.settings.data_dir)
    return summarize_validation(store, _collection(ctx), view)
```

Modify `src/opendomainmcp/api/app.py` imports:

```python
from . import (
    insight_routes,
    mcp_endpoints,
    quality_routes,
    source_routes,
    validation_routes,
    workspace_routes,
)
```

Add router include next to quality routes:

```python
    app.include_router(validation_routes.router)
```

- [ ] **Step 5: Run validation API tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_validation_api.py tests/test_integration_wiring.py::test_validation_routes_wired tests/test_integration_wiring.py::test_rbac_default_off_allows_simulate -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit validation API**

```bash
git add src/opendomainmcp/api/app.py src/opendomainmcp/api/simulation.py src/opendomainmcp/api/validation_routes.py tests/test_validation_api.py tests/test_integration_wiring.py
git commit -m "feat: add validation scenario api"
```

## Task 3: Quality Evidence And MCP Endpoint Integration

**Files:**
- Modify: `src/opendomainmcp/quality/evidence.py`
- Modify: `src/opendomainmcp/api/mcp_endpoints.py`
- Test: `tests/test_quality_evidence.py`
- Test: `tests/test_mcp_endpoints.py`

- [ ] **Step 1: Write failing quality evidence tests**

Modify `tests/test_quality_evidence.py`:

In `test_quality_evidence_returns_gate_cards_for_empty_collection`, update the evidence ids assertion:

```python
    assert [card["id"] for card in payload["evidence"]] == [
        "coverage",
        "review",
        "articles",
        "retrieval",
        "graph",
        "simulation",
        "jobs",
    ]
```

Add assertions:

```python
    assert _card(payload, "simulation") == {
        "id": "simulation",
        "gate": "Simulation",
        "status": "validating",
        "score": 0,
        "summary": "No validation scenarios have been run.",
        "details": ["0 scenarios", "0 latest runs", "0 passed", "0 failed"],
        "action": "Run validation scenarios in Agent Simulator.",
    }
```

Add this new test:

```python
def test_quality_evidence_summarizes_validation_runs(
    store, pipeline, fake_graph, tmp_path
):
    from opendomainmcp.validation import ValidationStore, build_run, build_scenario

    ctx = _ctx(store, pipeline, fake_graph, tmp_path)
    scenario = build_scenario(
        collection=store.stats()["collection"],
        view="product",
        name="Rollback",
        query="rollback",
    )
    validation = ValidationStore(tmp_path)
    validation.append_scenario(scenario)
    validation.append_run(
        build_run(
            collection=store.stats()["collection"],
            scenario=scenario,
            result={
                "view": "product",
                "grounding": {
                    "hits": 2,
                    "avg_score": 0.8,
                    "knowledge_types": ["Runbook"],
                },
                "tools": [{"tool": "search_features", "results": [{"id": "1"}]}],
            },
        )
    )

    payload = compute_quality_evidence(ctx, tasks=[])

    assert _card(payload, "simulation") == {
        "id": "simulation",
        "gate": "Simulation",
        "status": "ready",
        "score": 100,
        "summary": "1 validation scenario passed.",
        "details": ["1 scenario", "1 latest run", "1 passed", "0 failed"],
        "action": "Simulation gate is clear.",
    }
```

Add this failed-run test:

```python
def test_quality_evidence_blocks_on_failed_validation_run(
    store, pipeline, fake_graph, tmp_path
):
    from opendomainmcp.validation import ValidationStore, build_run, build_scenario

    ctx = _ctx(store, pipeline, fake_graph, tmp_path)
    scenario = build_scenario(
        collection=store.stats()["collection"],
        view="product",
        name="Rollback",
        query="rollback",
    )
    validation = ValidationStore(tmp_path)
    validation.append_scenario(scenario)
    validation.append_run(
        build_run(
            collection=store.stats()["collection"],
            scenario=scenario,
            result={"view": "product", "grounding": {"hits": 0}, "tools": []},
        )
    )

    payload = compute_quality_evidence(ctx, tasks=[])

    assert _card(payload, "simulation")["status"] == "blocked"
    assert _card(payload, "simulation")["summary"] == "1 validation scenario failed."
    assert payload["status"] == "blocked"
```

- [ ] **Step 2: Write failing MCP endpoint validation summary test**

Modify `tests/test_mcp_endpoints.py`:

Add import:

```python
from opendomainmcp.validation import ValidationStore, build_run, build_scenario
```

Add test:

```python
def test_list_endpoints_includes_validation_summary(
    store, pipeline, fake_graph, tmp_path
):
    scenario = build_scenario(
        collection=store.stats()["collection"],
        view="product",
        name="Rollback",
        query="rollback",
    )
    validation = ValidationStore(tmp_path)
    validation.append_scenario(scenario)
    validation.append_run(
        build_run(
            collection=store.stats()["collection"],
            scenario=scenario,
            result={
                "view": "product",
                "grounding": {"hits": 1, "avg_score": 0.9, "knowledge_types": []},
                "tools": [{"tool": "search_features", "results": [{"id": "1"}]}],
            },
        )
    )
    tc, _, _ = _make_client(store, pipeline, fake_graph, tmp_path)

    data = {entry["view"]: entry for entry in tc.get("/api/mcp/endpoints").json()}

    assert data["product"]["validation"]["status"] == "passed"
    assert data["product"]["validation"]["passed"] == 1
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_quality_evidence.py tests/test_mcp_endpoints.py::test_list_endpoints_includes_validation_summary -q
```

Expected: fail because Simulation card and endpoint `validation` field do not exist.

- [ ] **Step 4: Add Simulation gate**

Modify `src/opendomainmcp/quality/evidence.py`:

Import validation helpers:

```python
from ..validation import ValidationStore, summarize_validation
```

Insert `_simulation_card(ctx, readiness)` before `_jobs_card(readiness)` in `compute_quality_evidence`:

```python
        _simulation_card(ctx, readiness),
```

Add function:

```python
def _simulation_card(ctx: Context, readiness: dict) -> dict:
    summary = summarize_validation(
        ValidationStore(ctx.settings.data_dir),
        readiness["collection"],
    )
    scenarios = int(summary.get("scenario_count") or 0)
    latest_runs = int(summary.get("latest_run_count") or 0)
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    if latest_runs == 0:
        status, score = "validating", 0
        text = "No validation scenarios have been run."
        action = "Run validation scenarios in Agent Simulator."
    elif failed:
        status, score = "blocked", 0
        text = _count_label(failed, "validation scenario failed")
        action = "Inspect failed validation scenarios."
    else:
        status = "ready"
        score = round(float(summary.get("pass_rate") or 0.0) * 100)
        text = _count_label(passed, "validation scenario passed")
        action = "Simulation gate is clear."
    return {
        "id": "simulation",
        "gate": "Simulation",
        "status": status,
        "score": score,
        "summary": text,
        "details": [
            _plain_count(scenarios, "scenario"),
            _plain_count(latest_runs, "latest run"),
            _plain_count(passed, "passed"),
            _plain_count(failed, "failed"),
        ],
        "action": action,
    }
```

Update `_count_label`:

```python
def _count_label(count: int, singular: str) -> str:
    if count == 1:
        return f"1 {singular}."
    if singular == "background job failed":
        return f"{count} background jobs failed."
    if singular.endswith("failed") or singular.endswith("passed"):
        base = singular.rsplit(" ", 1)[0]
        state = singular.rsplit(" ", 1)[1]
        return f"{count} {base}s {state}."
    return f"{count} {singular}s."
```

Add helper:

```python
def _plain_count(count: int, singular: str) -> str:
    if singular in {"passed", "failed"}:
        return f"{count} {singular}"
    if count == 1:
        return f"1 {singular}"
    return f"{count} {singular}s"
```

- [ ] **Step 5: Add endpoint validation summary**

Modify `src/opendomainmcp/api/mcp_endpoints.py`:

Import:

```python
from ..validation import ValidationStore, summarize_validation
```

In `list_endpoints`, create validation store:

```python
    validation = ValidationStore(ctx.settings.data_dir)
```

Update `_entry` signature to accept `validation: ValidationStore`.

Add this field to `_entry` return:

```python
        "validation": summarize_validation(validation, collection, view),
```

Pass `validation` from list/publish/unpublish paths.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_quality_evidence.py tests/test_mcp_endpoints.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit quality and endpoint integration**

```bash
git add src/opendomainmcp/quality/evidence.py src/opendomainmcp/api/mcp_endpoints.py tests/test_quality_evidence.py tests/test_mcp_endpoints.py
git commit -m "feat: add simulation validation gate"
```

## Task 4: Frontend Validation Suite UI

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/pages/Simulator.tsx`
- Modify: `web/src/pages/McpBuilder.tsx`
- Modify: `web/tests/helpers/mockApi.ts`
- Modify: `web/tests/simulator.spec.ts`
- Modify: `web/tests/quality_lab.spec.ts`
- Modify: `web/tests/mcp_builder.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

Modify `web/tests/helpers/mockApi.ts`:

Add default validation summary:

```ts
export const DEFAULT_VALIDATION_SUMMARY = {
  collection: "default",
  view: null,
  status: "validating",
  scenario_count: 0,
  latest_run_count: 0,
  passed: 0,
  failed: 0,
  pass_rate: 0,
  latest_run: null,
};
```

Add Simulation gate to `DEFAULT_QUALITY_EVIDENCE.evidence`:

```ts
    {
      id: "simulation",
      gate: "Simulation",
      status: "validating",
      score: 0,
      summary: "No validation scenarios have been run.",
      details: ["0 scenarios", "0 latest runs", "0 passed", "0 failed"],
      action: "Run validation scenarios in Agent Simulator.",
    },
```

Add defaults:

```ts
    "GET /api/validation/scenarios": [],
    "GET /api/validation/summary": DEFAULT_VALIDATION_SUMMARY,
```

Modify `web/tests/simulator.spec.ts` with scenario payloads:

```ts
const SCENARIO = {
  id: "scenario-1",
  collection: "default",
  view: "operations",
  name: "Rollback",
  query: "How do I roll back a failed deployment?",
  created_at: 1814052000,
};

const RUN = {
  id: "run-1",
  scenario_id: "scenario-1",
  collection: "default",
  view: "operations",
  query: "How do I roll back a failed deployment?",
  status: "passed",
  grounding_hits: 3,
  avg_score: 0.812,
  tool_results: 2,
  knowledge_types: ["Runbook", "Workflow"],
  error: "",
  created_at: 1814052001,
};
```

Add mocks:

```ts
      "GET /api/validation/scenarios": [SCENARIO],
      "POST /api/validation/run": {
        scenario: SCENARIO,
        run: RUN,
        result: SIMULATE_RESULT,
        summary: {
          collection: "default",
          view: "operations",
          status: "passed",
          scenario_count: 1,
          latest_run_count: 1,
          passed: 1,
          failed: 0,
          pass_rate: 1,
          latest_run: RUN,
        },
      },
      "POST /api/validation/scenarios/scenario-1/run": RUN,
```

Add test:

```ts
  test("saves and runs validation scenarios", async ({ page }) => {
    await page.goto("/#/simulator");
    await expect(page.getByRole("heading", { name: "Validation scenarios" })).toBeVisible();
    await expect(page.getByText("Rollback")).toBeVisible();

    await page
      .getByPlaceholder("e.g. How do I roll back a failed deployment?")
      .fill("How do I roll back a failed deployment?");
    await page.locator("main select").selectOption({ label: "Operations View" });
    await page.getByRole("button", { name: "Simulate" }).click();

    await page.getByLabel("Scenario name").fill("Rollback");
    await page.getByRole("button", { name: "Save validation scenario" }).click();
    await expect(page.getByText("passed")).toBeVisible();

    await page.getByRole("button", { name: "Run scenario Rollback" }).click();
    await expect(page.getByText("latest passed")).toBeVisible();
  });
```

Modify `web/tests/quality_lab.spec.ts` gate list to include `"Simulation"`.

Modify `web/tests/mcp_builder.spec.ts` endpoint mocks to include:

```ts
    validation: {
      collection: "default",
      view: "product",
      status: "passed",
      scenario_count: 1,
      latest_run_count: 1,
      passed: 1,
      failed: 0,
      pass_rate: 1,
      latest_run: null,
    },
```

Add assertion:

```ts
    await expect(row.getByText("Validation passed")).toBeVisible();
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
npm run test:e2e -- tests/simulator.spec.ts tests/quality_lab.spec.ts tests/mcp_builder.spec.ts
```

Expected: fail because validation UI and API methods do not exist.

- [ ] **Step 3: Add frontend API types and methods**

Modify `web/src/api.ts`:

Add interfaces:

```ts
export interface ValidationScenario {
  id: string;
  collection: string;
  view: string;
  name: string;
  query: string;
  created_at: number;
}

export interface ValidationRun {
  id: string;
  scenario_id: string;
  collection: string;
  view: string;
  query: string;
  status: "passed" | "failed";
  grounding_hits: number;
  avg_score: number;
  tool_results: number;
  knowledge_types: string[];
  error: string;
  created_at: number;
}

export interface ValidationSummary {
  collection: string;
  view: string | null;
  status: "validating" | "passed" | "failed";
  scenario_count: number;
  latest_run_count: number;
  passed: number;
  failed: number;
  pass_rate: number;
  latest_run: ValidationRun | null;
}

export interface ValidationRunResponse {
  scenario: ValidationScenario;
  run: ValidationRun;
  result: SimulateResult;
  summary: ValidationSummary;
}
```

Add `validation` field to `McpEndpoint`:

```ts
  validation: ValidationSummary;
```

Add API methods:

```ts
  validationScenarios: (view?: string) => {
    const params = new URLSearchParams();
    if (view) params.set("view", view);
    const suffix = params.toString() ? `?${params}` : "";
    return fetch(withCollection(`/api/validation/scenarios${suffix}`), {
      headers: headers(),
    }).then(json<ValidationScenario[]>);
  },

  runValidationScenario: (id: string) =>
    fetch(withCollection(`/api/validation/scenarios/${encodeURIComponent(id)}/run`), {
      method: "POST",
      headers: headers(),
    }).then(json<ValidationRun>),

  runValidation: (view: string, query: string, name: string, top_k = 5) =>
    fetch(withCollection("/api/validation/run"), {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ view, query, name, top_k }),
    }).then(json<ValidationRunResponse>),

  validationSummary: (view?: string) => {
    const params = new URLSearchParams();
    if (view) params.set("view", view);
    const suffix = params.toString() ? `?${params}` : "";
    return fetch(withCollection(`/api/validation/summary${suffix}`), {
      headers: headers(),
    }).then(json<ValidationSummary>);
  },
```

- [ ] **Step 4: Implement Simulator validation UI**

Modify `web/src/pages/Simulator.tsx`:

Import validation types:

```ts
import { api, SimulateResult, ValidationRun, ValidationScenario, ViewsMap } from "../api";
```

Add state:

```ts
  const [scenarios, setScenarios] = useState<ValidationScenario[]>([]);
  const [scenarioRuns, setScenarioRuns] = useState<Record<string, ValidationRun>>({});
  const [scenarioName, setScenarioName] = useState("");
  const [savingScenario, setSavingScenario] = useState(false);
  const [runningScenario, setRunningScenario] = useState<string | null>(null);
```

Add load helper:

```ts
  async function loadScenarios(selectedView = view) {
    try {
      setScenarios(await api.validationScenarios(selectedView));
    } catch (e) {
      toast.show(String(e), "red");
    }
  }
```

Call it in `useEffect`:

```ts
    void loadScenarios();
```

Update select `onChange`:

```tsx
              onChange={(e) => {
                setView(e.target.value);
                void loadScenarios(e.target.value);
              }}
```

Add actions:

```ts
  async function saveScenario() {
    if (!result || !scenarioName.trim() || !task.trim()) return;
    setSavingScenario(true);
    try {
      const payload = await api.runValidation(view, task.trim(), scenarioName.trim());
      setResult(payload.result);
      setScenarios((prev) => {
        const without = prev.filter((s) => s.id !== payload.scenario.id);
        return [payload.scenario, ...without];
      });
      setScenarioRuns((prev) => ({ ...prev, [payload.scenario.id]: payload.run }));
      toast.show("Validation scenario saved", "green");
    } catch (e) {
      toast.show(String(e), "red");
    } finally {
      setSavingScenario(false);
    }
  }

  async function runSavedScenario(scenario: ValidationScenario) {
    setRunningScenario(scenario.id);
    try {
      const run = await api.runValidationScenario(scenario.id);
      setScenarioRuns((prev) => ({ ...prev, [scenario.id]: run }));
      toast.show(`Scenario ${run.status}`, run.status === "passed" ? "green" : "red");
    } catch (e) {
      toast.show(String(e), "red");
    } finally {
      setRunningScenario(null);
    }
  }
```

Render a `Validation scenarios` card after the input card and before `{result && ...}`:

```tsx
      <Card className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Validation scenarios
          </h3>
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
            Save representative tasks and rerun them before publishing this MCP view.
          </p>
        </div>
        {scenarios.length === 0 ? (
          <EmptyState
            icon={<IconSimulator className="h-6 w-6" />}
            title="No validation scenarios"
            hint="Run a simulation, name it, and save it as a reusable validation scenario."
          />
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {scenarios.map((scenario) => {
              const run = scenarioRuns[scenario.id];
              return (
                <div key={scenario.id} className="flex flex-wrap items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-900 dark:text-white">
                      {scenario.name}
                    </div>
                    <div className="truncate text-xs text-slate-400">
                      {scenario.query}
                    </div>
                    {run && (
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        latest {run.status} · {run.grounding_hits} hits
                      </div>
                    )}
                  </div>
                  {run && (
                    <Badge tone={run.status === "passed" ? "green" : "red"}>
                      {run.status}
                    </Badge>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={runningScenario === scenario.id}
                    disabled={runningScenario === scenario.id}
                    onClick={() => void runSavedScenario(scenario)}
                  >
                    Run scenario {scenario.name}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>
```

Render save controls inside the `{result && (...)}` fragment before the grounding summary:

```tsx
          <Card className="space-y-3 p-4">
            <div>
              <Label>Scenario name</Label>
              <input
                className="mt-1.5 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="e.g. Rollback guidance"
              />
            </div>
            <div className="flex justify-end">
              <Button
                onClick={saveScenario}
                loading={savingScenario}
                disabled={!scenarioName.trim()}
              >
                Save validation scenario
              </Button>
            </div>
          </Card>
```

- [ ] **Step 5: Implement MCP Publish validation summary**

Modify `web/src/pages/McpBuilder.tsx` inside `EndpointRow` after latest decision/no decision block:

```tsx
        <div className="rounded-lg border border-slate-100 p-3 text-xs dark:border-slate-800">
          <div className="font-medium text-slate-700 dark:text-slate-200">
            Validation {endpoint.validation.status}
          </div>
          <div className="mt-1 text-slate-500 dark:text-slate-400">
            {endpoint.validation.passed} passed · {endpoint.validation.failed} failed ·{" "}
            {endpoint.validation.scenario_count} scenarios
          </div>
        </div>
```

- [ ] **Step 6: Run frontend tests and verify GREEN**

Run:

```bash
npm run test:e2e -- tests/simulator.spec.ts tests/quality_lab.spec.ts tests/mcp_builder.spec.ts
```

Expected: all selected Playwright tests pass.

- [ ] **Step 7: Commit frontend validation UI**

```bash
git add web/src/api.ts web/src/pages/Simulator.tsx web/src/pages/McpBuilder.tsx web/tests/helpers/mockApi.ts web/tests/simulator.spec.ts web/tests/quality_lab.spec.ts web/tests/mcp_builder.spec.ts
git commit -m "feat(web): add validation scenario workflow"
```

## Task 5: Documentation And Final Verification

**Files:**
- Modify: `docs/DEVLOG.md`
- Modify: `docs/TASKS.md`
- Generated: `docs/*.html` if the docs build updates them.

- [ ] **Step 1: Record Wave 4A docs**

Add a new `Enterprise Redesign Wave 4A` section to `docs/TASKS.md` with:

```markdown
## ✅ Enterprise Redesign Wave 4A（已完成，2026-06-28）

建立第一個 Validation Scenario Suite 可交付切片：把一次性的 Agent Simulator 任務升級為可保存、可重跑、可進 Quality Evidence 的 validation scenario/run 紀錄。設計與計畫見 `docs/superpowers/specs/2026-06-28-enterprise-wave-4a-validation-suite-design.md`、`docs/superpowers/plans/2026-06-28-enterprise-wave-4a-validation-suite.md`。

| # | 狀態 | Effort | 任務 | 內容 | 位置 |
|---|------|--------|------|------|------|
| E4A.1 | ✅ | Low | Validation scenario store | file-backed `validation_runs.json`，依 collection/view 保存 scenarios 與 runs | `src/opendomainmcp/validation/store.py`、`tests/test_validation_store.py` |
| E4A.2 | ✅ | Medium | Validation API | scenario create/list/run/summary API，重用 simulator executor | `src/opendomainmcp/api/validation_routes.py`、`src/opendomainmcp/api/simulation.py`、`tests/test_validation_api.py` |
| E4A.3 | ✅ | Medium | Simulation quality gate | Quality Evidence 新增 Simulation gate，MCP endpoint rows 帶 validation summary | `src/opendomainmcp/quality/evidence.py`、`src/opendomainmcp/api/mcp_endpoints.py` |
| E4A.4 | ✅ | Medium | Simulator validation workflow | Simulator 可保存/重跑 validation scenarios，MCP Publish 顯示 validation summary | `web/src/pages/Simulator.tsx`、`web/src/pages/McpBuilder.tsx` |
| E4A.5 | ✅ | Low | Wave 4A docs and verification | 紀錄 validation suite 範圍與驗證結果 | `docs/DEVLOG.md`、`docs/TASKS.md` |
```

Add a concise Wave 4A entry to `docs/DEVLOG.md` describing scope and verification.

- [ ] **Step 2: Rebuild docs if needed**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python docs/build.py
```

Expected: docs HTML regenerates successfully.

- [ ] **Step 3: Run full verification**

Run:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest -q
npm run build
npm run test:e2e
```

Expected:

- Backend pytest passes.
- Vite build passes.
- Playwright e2e passes.

- [ ] **Step 4: Commit docs**

```bash
git add docs/DEVLOG.md docs/TASKS.md docs/*.html
git commit -m "docs: record enterprise wave 4a"
```

## Plan Self-Review

- Spec coverage: The plan covers file-backed validation storage, scenario/run APIs, simulator reuse, Quality Evidence Simulation gate, MCP Publish validation summary, Simulator UI controls, tests, docs, and verification.
- Scope control: The plan does not add external scheduling, LLM judging, queue replacement, database migration, or FastMCP transport changes.
- TDD coverage: Each production change starts with focused failing tests and an explicit RED command.
- Type consistency: Backend statuses are `validating`, `passed`, and `failed` for validation summaries; Quality Evidence maps them to existing readiness statuses `validating`, `ready`, and `blocked`.
