# Enterprise Wave 1 Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Wave 1 of the enterprise redesign: stabilize the test harness, introduce a backend readiness summary, and reshape the first-screen workflow around Command Center and Source Intake.

**Architecture:** Keep the existing FastAPI/React/Chroma/MariaDB architecture. Add a small `quality.readiness` domain service and a thin `workspace_routes` router, then consume that from a new Command Center page. Source Intake reuses existing upload, ingest, task, and source registry APIs instead of creating a second ingestion path.

**Tech Stack:** Python 3.11, FastAPI, pytest, React 18, TypeScript, Vite, Playwright, Tailwind.

---

## Scope Check

The approved blueprint covers 8-12 weeks and multiple independent subsystems. This implementation plan covers **Wave 1 only**:

- Command Center
- Source Intake
- lifecycle/readiness summary
- source health summary
- Task Center summary integration
- E2E and pytest stability fixes

This plan does not implement Wave 2 Quality Lab/readiness gates or Wave 3 publish governance/job backend replacement. Those need separate plans after Wave 1 is reviewed.

## File Structure

- Create `tests/__init__.py`
  - Makes `tests.conftest` importable for the direct `.venv/bin/pytest` launcher.

- Modify `web/tests/helpers/mockApi.ts`
  - Adds stable defaults for `/api/tasks` and `/api/workspace/readiness`.

- Modify `web/src/components/TaskCenter.tsx`
  - Defensively handles malformed task-list responses so one bad API/mock response cannot crash the layout.

- Create `src/opendomainmcp/quality/__init__.py`
  - Exports readiness model helpers.

- Create `src/opendomainmcp/quality/readiness.py`
  - Computes a first-pass knowledge-base readiness summary from store stats, sources, graph availability, and task state.

- Create `src/opendomainmcp/api/workspace_routes.py`
  - Exposes `GET /api/workspace/readiness`.

- Modify `src/opendomainmcp/api/app.py`
  - Mounts the workspace router.

- Create `tests/test_workspace_readiness.py`
  - Verifies readiness status, source/review/job health, and API wiring.

- Modify `web/src/api.ts`
  - Adds `KnowledgeBaseReadiness`, `TaskList`, and `api.workspaceReadiness()`.
  - Makes `api.listTasks()` normalize missing task arrays.

- Create `web/src/pages/CommandCenter.tsx`
  - New first screen for lifecycle status, blockers, sources, review health, jobs, and next action.

- Create `web/src/pages/SourceIntake.tsx`
  - New intake workspace combining path/upload ingestion and source registry management.

- Modify `web/src/main.tsx`
  - Routes `/` to `CommandCenter`; routes `/intake` and `/ingest` to `SourceIntake`.

- Modify `web/src/App.tsx`
  - Updates the primary nav labels for Wave 1 while keeping old routes accessible.

- Modify `web/tests/smoke.spec.ts`
  - Updates sidebar and Command Center assertions.

- Create `web/tests/source_intake.spec.ts`
  - Verifies intake path, source registry, and background task launch.

---

### Task 1: Stabilize Existing Test Harness

**Files:**
- Create: `tests/__init__.py`
- Modify: `web/tests/helpers/mockApi.ts`
- Modify: `web/src/components/TaskCenter.tsx`
- Test: existing `tests/test_graph_collection_scope.py`
- Test: existing `web/tests/*.spec.ts`

- [ ] **Step 1: Reproduce the backend launcher failure**

Run:

```bash
.venv/bin/pytest tests/test_graph_collection_scope.py -q
```

Expected before the fix:

```text
ModuleNotFoundError: No module named 'tests'
```

- [ ] **Step 2: Make `tests` importable for both pytest launchers**

Create `tests/__init__.py` with exactly this content:

```python
"""Test package marker.

Some tests import shared fakes via ``tests.conftest``. Keeping ``tests`` as an
explicit package makes that import stable for both ``python -m pytest`` and the
direct ``.venv/bin/pytest`` console-script launcher.
"""
```

- [ ] **Step 3: Verify the backend launcher fix**

Run:

```bash
.venv/bin/pytest tests/test_graph_collection_scope.py -q
```

Expected after the fix:

```text
2 passed
```

- [ ] **Step 4: Reproduce the frontend layout crash**

Run:

```bash
npm run test:e2e
```

Expected before the fix:

```text
Unexpected Application Error!
Cannot read properties of undefined (reading 'filter')
```

The crash comes from `TaskCenter` receiving `{}` for the unmocked `GET /api/tasks` route.

- [ ] **Step 5: Add stable API mock defaults**

In `web/tests/helpers/mockApi.ts`, add this constant after `DEFAULT_GRAPH_WORKFLOWS`:

```ts
export const DEFAULT_TASKS = {
  tasks: [],
};

export const DEFAULT_READINESS = {
  collection: "default",
  status: "needs_review",
  score: 72,
  next_action: "Review pending knowledge before publishing MCP views.",
  blockers: [],
  warnings: ["2 sources need review"],
  stats: {
    count: 1234,
    embedder: "all-MiniLM-L6-v2",
    dim: 384,
  },
  source_health: {
    sources: 2,
    chunks: 60,
    stale: 0,
    failed: 0,
  },
  review_health: {
    approved: 48,
    pending: 10,
    rejected: 2,
    unset: 0,
    approved_ratio: 0.8,
  },
  job_health: {
    queued: 0,
    running: 0,
    done: 3,
    error: 0,
    cancelled: 0,
  },
  graph_health: {
    available: true,
    entities: 2,
    workflows: 1,
  },
};
```

Then update `buildDefaults()` so it contains:

```ts
    "GET /api/tasks": DEFAULT_TASKS,
    "GET /api/workspace/readiness": DEFAULT_READINESS,
```

- [ ] **Step 6: Normalize task responses in the API client**

In `web/src/api.ts`, add this interface near `TaskItem`:

```ts
export interface TaskList {
  tasks: TaskItem[];
}
```

Then replace `listTasks` with:

```ts
  listTasks: () =>
    fetch(withCollection("/api/tasks"), { headers: headers() })
      .then(json<Partial<TaskList>>)
      .then((body) => ({
        tasks: Array.isArray(body.tasks) ? body.tasks : [],
      })),
```

- [ ] **Step 7: Make Task Center defensive at the component boundary**

In `web/src/components/TaskCenter.tsx`, replace the `refresh` callback body with:

```ts
  const refresh = useCallback(async () => {
    try {
      const body = await api.listTasks();
      setTasks(Array.isArray(body.tasks) ? body.tasks : []);
    } catch {
      /* transient */
    }
  }, []);
```

- [ ] **Step 8: Verify frontend stability**

Run:

```bash
npm run test:e2e
```

Expected after this task:

```text
10 passed
```

If later tasks intentionally change navigation text, this exact count may change after test updates. At this task boundary, all current E2E tests should pass.

- [ ] **Step 9: Verify full backend test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected:

```text
421 passed, 3 skipped
```

- [ ] **Step 10: Commit**

```bash
git add tests/__init__.py web/tests/helpers/mockApi.ts web/src/api.ts web/src/components/TaskCenter.tsx
git commit -m "test: stabilize pytest and task center e2e harness"
```

---

### Task 2: Add Backend Readiness Service

**Files:**
- Create: `src/opendomainmcp/quality/__init__.py`
- Create: `src/opendomainmcp/quality/readiness.py`
- Test: `tests/test_workspace_readiness.py`

- [ ] **Step 1: Write failing unit tests for readiness computation**

Create `tests/test_workspace_readiness.py` with:

```python
from __future__ import annotations

from opendomainmcp.config import Settings
from opendomainmcp.context import Context
from opendomainmcp.models import Chunk, KnowledgeUnit
from opendomainmcp.quality.readiness import compute_readiness


def _ctx(store, pipeline, fake_graph, tmp_path):
    settings = Settings(data_dir=tmp_path)
    return Context(settings=settings, store=store, pipeline=pipeline, graph=fake_graph)


def test_empty_collection_is_blocked(store, pipeline, fake_graph, tmp_path):
    ctx = _ctx(store, pipeline, fake_graph, tmp_path)

    data = compute_readiness(ctx, tasks=[])

    assert data["status"] == "blocked"
    assert data["score"] == 0
    assert data["blockers"] == ["No indexed knowledge objects."]
    assert data["next_action"] == "Add sources in Source Intake."


def test_pending_review_marks_collection_needs_review(store, pipeline, fake_graph, tmp_path):
    ctx = _ctx(store, pipeline, fake_graph, tmp_path)
    store.upsert([
        Chunk(
            text="Approved workflow",
            source="runbook.md",
            kind="text",
            knowledge=KnowledgeUnit(summary="ok", review_status="approved"),
        ),
        Chunk(
            text="Pending policy",
            source="policy.md",
            kind="text",
            knowledge=KnowledgeUnit(summary="pending", review_status="pending"),
        ),
    ])

    data = compute_readiness(ctx, tasks=[])

    assert data["status"] == "needs_review"
    assert data["review_health"]["approved"] == 1
    assert data["review_health"]["pending"] == 1
    assert data["review_health"]["approved_ratio"] == 0.5
    assert data["warnings"] == ["1 knowledge object is pending review."]


def test_failed_jobs_block_readiness(store, pipeline, fake_graph, tmp_path):
    ctx = _ctx(store, pipeline, fake_graph, tmp_path)
    store.upsert([
        Chunk(
            text="Approved workflow",
            source="runbook.md",
            kind="text",
            knowledge=KnowledgeUnit(summary="ok", review_status="approved"),
        ),
    ])

    data = compute_readiness(
        ctx,
        tasks=[{"status": "error"}, {"status": "done"}],
    )

    assert data["status"] == "blocked"
    assert data["job_health"]["error"] == 1
    assert data["blockers"] == ["1 background job failed."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_workspace_readiness.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'opendomainmcp.quality'
```

- [ ] **Step 3: Create the quality package export**

Create `src/opendomainmcp/quality/__init__.py`:

```python
"""Quality and readiness helpers for enterprise workspace decisions."""

from .readiness import compute_readiness

__all__ = ["compute_readiness"]
```

- [ ] **Step 4: Implement readiness computation**

Create `src/opendomainmcp/quality/readiness.py`:

```python
from __future__ import annotations

from collections import Counter
from typing import Iterable

from ..context import Context

TERMINAL_JOB_STATUSES = ("done", "error", "cancelled")
ALL_JOB_STATUSES = ("queued", "running", "done", "error", "cancelled")


def compute_readiness(ctx: Context, tasks: Iterable[dict] | None = None) -> dict:
    """Return an explainable readiness summary for the active knowledge base."""
    stats = ctx.store.stats()
    sources = ctx.store.list_sources()
    task_rows = list(tasks or [])

    review = _review_health(sources)
    source = _source_health(sources)
    jobs = _job_health(task_rows)
    graph = _graph_health(ctx)

    blockers: list[str] = []
    warnings: list[str] = []

    if int(stats.get("count", 0) or 0) == 0:
        blockers.append("No indexed knowledge objects.")
    if jobs["error"]:
        blockers.append(_plural(jobs["error"], "background job failed", "background jobs failed"))
    if review["pending"]:
        warnings.append(_plural(review["pending"], "knowledge object is pending review", "knowledge objects are pending review"))
    if review["rejected"]:
        warnings.append(_plural(review["rejected"], "knowledge object was rejected", "knowledge objects were rejected"))
    if not graph["available"]:
        warnings.append("Graph store is unavailable.")

    if blockers:
        status = "blocked"
    elif review["pending"] or review["approved_ratio"] < 0.8:
        status = "needs_review"
    else:
        status = "ready"

    score = _score(stats, review, jobs, graph)
    return {
        "collection": stats.get("collection", ""),
        "status": status,
        "score": score,
        "next_action": _next_action(status, blockers, warnings),
        "blockers": blockers,
        "warnings": warnings,
        "stats": {
            "count": int(stats.get("count", 0) or 0),
            "embedder": stats.get("embedder", ""),
            "dim": int(stats.get("dim", 0) or 0),
        },
        "source_health": source,
        "review_health": review,
        "job_health": jobs,
        "graph_health": graph,
    }


def _source_health(sources: list[dict]) -> dict:
    return {
        "sources": len(sources),
        "chunks": sum(int(s.get("chunks", 0) or 0) for s in sources),
        "stale": 0,
        "failed": 0,
    }


def _review_health(sources: list[dict]) -> dict:
    counts = Counter()
    for src in sources:
        review = src.get("review") or {}
        for key in ("approved", "pending", "rejected", "unset"):
            counts[key] += int(review.get(key, 0) or 0)
    total = counts["approved"] + counts["pending"] + counts["rejected"] + counts["unset"]
    ratio = round(counts["approved"] / total, 4) if total else 0.0
    return {
        "approved": counts["approved"],
        "pending": counts["pending"],
        "rejected": counts["rejected"],
        "unset": counts["unset"],
        "approved_ratio": ratio,
    }


def _job_health(tasks: list[dict]) -> dict:
    counts = Counter(t.get("status", "") for t in tasks)
    return {status: int(counts.get(status, 0)) for status in ALL_JOB_STATUSES}


def _graph_health(ctx: Context) -> dict:
    try:
        entities = ctx.graph.list_entities(limit=1)
        workflows = ctx.graph.list_workflows(limit=1)
        return {
            "available": True,
            "entities": len(entities),
            "workflows": len(workflows),
        }
    except Exception:
        return {"available": False, "entities": 0, "workflows": 0}


def _score(stats: dict, review: dict, jobs: dict, graph: dict) -> int:
    if int(stats.get("count", 0) or 0) == 0:
        return 0
    score = 45
    score += int(review["approved_ratio"] * 35)
    if graph["available"]:
        score += 10
    if jobs["error"] == 0:
        score += 10
    return max(0, min(100, score))


def _next_action(status: str, blockers: list[str], warnings: list[str]) -> str:
    if "No indexed knowledge objects." in blockers:
        return "Add sources in Source Intake."
    if blockers:
        return "Resolve readiness blockers before publishing MCP views."
    if status == "needs_review":
        return "Review pending knowledge before publishing MCP views."
    if warnings:
        return "Review warnings, then validate MCP scenarios."
    return "Validate MCP scenarios and prepare publish approval."


def _plural(count: int, singular: str, plural: str) -> str:
    word = singular if count == 1 else plural
    return f"{count} {word}."
```

- [ ] **Step 5: Run readiness unit tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_workspace_readiness.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit**

```bash
git add src/opendomainmcp/quality/__init__.py src/opendomainmcp/quality/readiness.py tests/test_workspace_readiness.py
git commit -m "feat(quality): compute workspace readiness summary"
```

---

### Task 3: Expose Workspace Readiness API

**Files:**
- Create: `src/opendomainmcp/api/workspace_routes.py`
- Modify: `src/opendomainmcp/api/app.py`
- Modify: `tests/test_workspace_readiness.py`

- [ ] **Step 1: Add failing API test**

Append this test to `tests/test_workspace_readiness.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opendomainmcp.api import workspace_routes


def test_workspace_readiness_route_returns_summary(store, pipeline, fake_graph, tmp_path):
    ctx = _ctx(store, pipeline, fake_graph, tmp_path)
    app = FastAPI()
    app.state.context = ctx
    app.include_router(workspace_routes.router)
    tc = TestClient(app)

    resp = tc.get("/api/workspace/readiness")

    assert resp.status_code == 200
    body = resp.json()
    assert body["collection"] == ctx.store.stats()["collection"]
    assert body["status"] == "blocked"
    assert body["source_health"]["sources"] == 0
```

- [ ] **Step 2: Run API test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_workspace_readiness.py::test_workspace_readiness_route_returns_summary -q
```

Expected:

```text
ImportError: cannot import name 'workspace_routes'
```

- [ ] **Step 3: Create workspace router**

Create `src/opendomainmcp/api/workspace_routes.py`:

```python
"""Workspace-level routes for Command Center decisions."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import Context
from ..quality import compute_readiness
from .deps import get_ctx

router = APIRouter()


@router.get("/api/workspace/readiness")
def workspace_readiness(ctx: Context = Depends(get_ctx)) -> dict:
    return compute_readiness(ctx, tasks=_task_rows(ctx))


def _task_rows(ctx: Context) -> list[dict]:
    from ..tasks.store import TaskStore

    store = TaskStore(ctx.settings.data_dir)
    return [t.to_dict() for t in store.list()]
```

- [ ] **Step 4: Mount router in the app**

In `src/opendomainmcp/api/app.py`, update the router import:

```python
from . import insight_routes, mcp_endpoints, source_routes, workspace_routes
```

Then, just before `app.include_router(insight_routes.router)`, add:

```python
    app.include_router(workspace_routes.router)
```

- [ ] **Step 5: Run workspace readiness API tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_workspace_readiness.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Run integration wiring smoke**

Run:

```bash
.venv/bin/python -m pytest tests/test_integration_wiring.py tests/test_observability.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
git add src/opendomainmcp/api/app.py src/opendomainmcp/api/workspace_routes.py tests/test_workspace_readiness.py
git commit -m "feat(api): expose workspace readiness endpoint"
```

---

### Task 4: Add Frontend Readiness Client Types

**Files:**
- Modify: `web/src/api.ts`
- Test: `web/tests/smoke.spec.ts`

- [ ] **Step 1: Replace smoke spec with Wave 1 homepage assertions**

Replace `web/tests/smoke.spec.ts` with:

```ts
import { expect, test } from "@playwright/test";
import { installApiMocks } from "./helpers/mockApi";

const NAV_LABELS = [
  "Command Center",
  "Source Intake",
  "Explore",
  "Ask",
  "Browse / Edit",
  "Articles",
  "Review",
  "Graph",
  "Advisor",
  "MCP Builder",
  "Simulator",
  "Metrics",
  "Settings",
];

test.describe("command center smoke", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page);
  });

  test("renders every sidebar nav link", async ({ page }) => {
    await page.goto("/");

    const sidebar = page.locator("aside");
    for (const label of NAV_LABELS) {
      await expect(
        sidebar.getByRole("link", { name: label, exact: true }),
      ).toBeVisible();
    }
  });

  test("renders command center readiness", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Command Center", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("needs review", { exact: true })).toBeVisible();
    await expect(page.getByText("72", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Review pending knowledge before publishing MCP views."),
    ).toBeVisible();
  });

  test("shows source, review, job, and graph health summaries", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText("Sources")).toBeVisible();
    await expect(page.getByText("2")).toBeVisible();
    await expect(page.getByText("60 chunks")).toBeVisible();
    await expect(page.getByText("Approved")).toBeVisible();
    await expect(page.getByText("80%")).toBeVisible();
    await expect(page.getByText("10 pending")).toBeVisible();
    await expect(page.getByText("Jobs")).toBeVisible();
    await expect(page.getByText("0 active")).toBeVisible();
    await expect(page.getByText("Graph")).toBeVisible();
    await expect(page.getByText("available")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the smoke test to verify it fails before implementation**

Run:

```bash
npm run test:e2e -- tests/smoke.spec.ts
```

Expected:

```text
Error: expect(locator).toBeVisible() failed
Locator: getByRole('heading', { name: 'Command Center', exact: true })
```

- [ ] **Step 3: Add readiness interfaces and API method**

In `web/src/api.ts`, add these interfaces after `MetricsView`:

```ts
export interface KnowledgeBaseReadiness {
  collection: string;
  status: "blocked" | "needs_review" | "validating" | "ready" | "published";
  score: number;
  next_action: string;
  blockers: string[];
  warnings: string[];
  stats: {
    count: number;
    embedder: string;
    dim: number;
  };
  source_health: {
    sources: number;
    chunks: number;
    stale: number;
    failed: number;
  };
  review_health: {
    approved: number;
    pending: number;
    rejected: number;
    unset: number;
    approved_ratio: number;
  };
  job_health: {
    queued: number;
    running: number;
    done: number;
    error: number;
    cancelled: number;
  };
  graph_health: {
    available: boolean;
    entities: number;
    workflows: number;
  };
}
```

Then add this method inside `api`:

```ts
  workspaceReadiness: () =>
    fetch(withCollection("/api/workspace/readiness"), { headers: headers() }).then(
      json<KnowledgeBaseReadiness>
    ),
```

- [ ] **Step 4: Verify TypeScript still compiles**

Run:

```bash
npm run build
```

Expected:

```text
✓ built
```

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/tests/smoke.spec.ts
git commit -m "feat(web): add workspace readiness api client"
```

---

### Task 5: Build Command Center First Screen

**Files:**
- Create: `web/src/pages/CommandCenter.tsx`
- Modify: `web/src/main.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/tests/smoke.spec.ts`

- [ ] **Step 1: Create Command Center page**

Create `web/src/pages/CommandCenter.tsx`:

```tsx
import { ReactNode, useEffect, useState } from "react";
import { api, KnowledgeBaseReadiness } from "../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton,
  useToast,
} from "../components/ui";
import {
  IconDashboard,
  IconDatabase,
  IconIngest,
  IconMetrics,
  IconReview,
  IconSparkle,
} from "../components/icons";

const STATUS_LABELS: Record<KnowledgeBaseReadiness["status"], string> = {
  blocked: "blocked",
  needs_review: "needs review",
  validating: "validating",
  ready: "ready",
  published: "published",
};

const STATUS_TONES: Record<KnowledgeBaseReadiness["status"], "red" | "amber" | "brand" | "green"> = {
  blocked: "red",
  needs_review: "amber",
  validating: "brand",
  ready: "green",
  published: "green",
};

export default function CommandCenter() {
  const [data, setData] = useState<KnowledgeBaseReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.workspaceReadiness());
    } catch (e) {
      const message = String(e);
      setError(message);
      toast.show(message, "red");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Command Center"
        subtitle="Lifecycle status, blockers, and next action for the active knowledge base."
        icon={<IconDashboard />}
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} loading={loading}>
            Refresh
          </Button>
        }
      />

      {error && (
        <Card className="border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </Card>
      )}

      {!data && !error && <LoadingGrid />}

      {data && (
        <>
          <Card className="p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                    {data.collection}
                  </h3>
                  <Badge tone={STATUS_TONES[data.status]}>
                    {STATUS_LABELS[data.status]}
                  </Badge>
                </div>
                <p className="mt-2 max-w-2xl text-sm text-slate-500 dark:text-slate-400">
                  {data.next_action}
                </p>
              </div>
              <div className="text-right">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  Readiness
                </div>
                <div className="text-4xl font-semibold text-brand-600 dark:text-brand-400">
                  {data.score}
                </div>
              </div>
            </div>
          </Card>

          {(data.blockers.length > 0 || data.warnings.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              <IssueList title="Blockers" tone="red" items={data.blockers} />
              <IssueList title="Warnings" tone="amber" items={data.warnings} />
            </div>
          )}

          <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Stat
              icon={<IconDatabase className="h-4 w-4" />}
              label="Sources"
              value={data.source_health.sources.toLocaleString()}
              detail={`${data.source_health.chunks.toLocaleString()} chunks`}
            />
            <Stat
              icon={<IconReview className="h-4 w-4" />}
              label="Approved"
              value={`${Math.round(data.review_health.approved_ratio * 100)}%`}
              detail={`${data.review_health.pending.toLocaleString()} pending`}
            />
            <Stat
              icon={<IconSparkle className="h-4 w-4" />}
              label="Jobs"
              value={`${data.job_health.running + data.job_health.queued} active`}
              detail={`${data.job_health.error} failed`}
            />
            <Stat
              icon={<IconMetrics className="h-4 w-4" />}
              label="Graph"
              value={data.graph_health.available ? "available" : "offline"}
              detail={`${data.graph_health.entities} entities, ${data.graph_health.workflows} workflows`}
            />
          </section>

          <Card className="p-5">
            <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Next workflow step
            </h3>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant={data.status === "blocked" ? "primary" : "secondary"} onClick={() => { window.location.hash = "#/intake"; }}>
                <IconIngest className="h-4 w-4" />
                Source Intake
              </Button>
              <Button variant="secondary" onClick={() => { window.location.hash = "#/review"; }}>
                <IconReview className="h-4 w-4" />
                Review Knowledge
              </Button>
              <Button variant="secondary" onClick={() => { window.location.hash = "#/metrics"; }}>
                <IconMetrics className="h-4 w-4" />
                Quality Signals
              </Button>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function LoadingGrid() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} className="p-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-3 h-8 w-16" />
        </Card>
      ))}
    </div>
  );
}

function IssueList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "red" | "amber";
  items: string[];
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        title={`No ${title.toLowerCase()}`}
        hint="No action required for this category."
      />
    );
  }
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Badge tone={tone}>{title}</Badge>
      </div>
      <ul className="space-y-1 text-sm text-slate-600 dark:text-slate-300">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Card>
  );
}

function Stat({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  detail: string;
}) {
  return (
    <Card interactive className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1.5 break-words text-lg font-semibold text-slate-900 dark:text-white">
        {value}
      </div>
      <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">
        {detail}
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: Route the home page to Command Center**

In `web/src/main.tsx`, import the page:

```tsx
import CommandCenter from "./pages/CommandCenter";
import SourceIntake from "./pages/SourceIntake";
```

Then replace the index route and ingest route entries with:

```tsx
      { index: true, element: <CommandCenter /> },
      { path: "intake", element: <SourceIntake /> },
      { path: "ingest", element: <SourceIntake /> },
```

Keep all other existing routes unchanged.

- [ ] **Step 3: Update primary navigation labels**

In `web/src/App.tsx`, change the first two entries in `links` to:

```tsx
  { to: "/", label: "Command Center", end: true, icon: IconDashboard },
  { to: "/intake", label: "Source Intake", icon: IconIngest },
```

Do not remove the other links in this task; they remain accessible while later waves consolidate them into workspaces.

- [ ] **Step 4: Run Command Center smoke test**

Run:

```bash
npm run test:e2e -- tests/smoke.spec.ts
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/CommandCenter.tsx web/src/main.tsx web/src/App.tsx web/tests/smoke.spec.ts
git commit -m "feat(web): add command center workspace"
```

---

### Task 6: Build Source Intake Workspace

**Files:**
- Create: `web/src/pages/SourceIntake.tsx`
- Modify: `web/tests/source_intake.spec.ts`

- [ ] **Step 1: Write failing Source Intake E2E test**

Create `web/tests/source_intake.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { installApiMocks } from "./helpers/mockApi";

test.describe("source intake", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page, {
      "POST /api/tasks": {
        id: "task-1",
        type: "ingest",
        title: "Ingest /repo/docs",
        collection: "default",
        status: "queued",
        total: 0,
        done: 0,
        failures: [],
        error: null,
        result: null,
      },
      "DELETE /api/sources": { deleted: 42, source: "docs/deploy.md" },
    });
  });

  test("queues ingest and shows source registry", async ({ page }) => {
    await page.goto("/#/intake");

    await expect(
      page.getByRole("heading", { name: "Source Intake" }),
    ).toBeVisible();
    await expect(page.getByText("docs/deploy.md")).toBeVisible();

    await page.getByPlaceholder("/path/to/code-or-docs").fill("/repo/docs");
    await page.getByRole("button", { name: "Run in background" }).click();
    await expect(
      page.getByText("Queued in Task Center", { exact: false }),
    ).toBeVisible();
  });
});
```

- [ ] **Step 2: Run Source Intake E2E to verify it fails**

Run:

```bash
npm run test:e2e -- tests/source_intake.spec.ts
```

Expected:

```text
Error: getByRole('heading', { name: 'Source Intake' }) not found
```

- [ ] **Step 3: Create Source Intake page**

Create `web/src/pages/SourceIntake.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { api, SourceInfo, ingestStream } from "../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  IconButton,
  Input,
  Label,
  Modal,
  PageHeader,
  Skeleton,
  useToast,
} from "../components/ui";
import { IconIngest, IconTrash, IconUpload } from "../components/icons";

interface LogLine {
  stage: string;
  text: string;
}

interface Report {
  files_indexed: number;
  chunks_indexed: number;
  chunks_pruned: number;
  skipped: { path: string; reason: string }[];
  errors: { path: string; error: string }[];
}

export default function SourceIntake() {
  const [path, setPath] = useState("");
  const [sync, setSync] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<LogLine[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [sources, setSources] = useState<SourceInfo[] | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SourceInfo | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();

  async function loadSources() {
    try {
      setSources((await api.sources()).sources);
    } catch {
      setSources([]);
    }
  }

  useEffect(() => {
    void loadSources();
  }, []);

  function runForeground(target: string) {
    setLog([]);
    setReport(null);
    setRunning(true);
    ingestStream(
      target,
      (event) => {
        const stage = String(event.stage ?? "");
        if (stage === "report") {
          setReport(event as unknown as Report);
          void loadSources();
          return;
        }
        setLog((prev) => [
          ...prev,
          { stage, text: `${event.path ?? ""} ${event.detail ?? ""}`.trim() },
        ]);
      },
      () => setRunning(false),
      sync,
    );
  }

  async function runBackground(target: string) {
    try {
      await api.createTask("ingest", { path: target, sync });
      toast.show("Queued in Task Center (top-right)", "green");
    } catch (e) {
      toast.show(String(e), "red");
    }
  }

  async function uploadAndRun() {
    const files = fileInput.current?.files;
    if (!files || files.length === 0) return;
    try {
      const { path: staged } = await api.upload(files);
      runForeground(staged);
    } catch (e) {
      toast.show(String(e), "red");
    }
  }

  async function deleteSource() {
    if (!pendingDelete) return;
    try {
      const source = pendingDelete.source;
      const result = await api.deleteSource(source);
      toast.show(`Removed ${source} (${result.deleted} chunks)`, "green");
      setPendingDelete(null);
      await loadSources();
    } catch (e) {
      toast.show(String(e), "red");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Source Intake"
        subtitle="Add, sync, and monitor sources for the active knowledge base."
        icon={<IconIngest />}
      />

      <Card className="space-y-3 p-5">
        <Label>Server path</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            className="flex-1 font-mono"
            placeholder="/path/to/code-or-docs"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && path && !running && runForeground(path)}
          />
          <Button disabled={!path || running} loading={running} onClick={() => runForeground(path)}>
            Ingest now
          </Button>
          <Button variant="secondary" disabled={!path || running} onClick={() => runBackground(path)}>
            Run in background
          </Button>
        </div>
        <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500 dark:border-slate-600 dark:bg-slate-800"
            checked={sync}
            onChange={(e) => setSync(e.target.checked)}
          />
          Sync directory and prune deleted files
        </label>
      </Card>

      <Card className="space-y-3 p-5">
        <Label>Upload files</Label>
        <input
          ref={fileInput}
          type="file"
          multiple
          onChange={(e) => setPicked(e.target.files ? Array.from(e.target.files).map((f) => f.name) : [])}
        />
        {picked.length > 0 && (
          <p className="truncate text-xs text-slate-400">{picked.join(", ")}</p>
        )}
        <Button variant="secondary" disabled={running || picked.length === 0} onClick={uploadAndRun}>
          <IconUpload className="h-4 w-4" />
          Upload & ingest
        </Button>
      </Card>

      {(running || log.length > 0) && (
        <Card className="overflow-hidden p-0">
          <div className="border-b border-slate-200 px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-400 dark:border-slate-800">
            Live log
          </div>
          <div className="scroll-thin h-48 overflow-auto bg-slate-950 p-4 font-mono text-xs">
            {log.map((line, i) => (
              <div key={`${i}-${line.stage}`} className="flex gap-2">
                <span className="shrink-0 text-brand-300">[{line.stage}]</span>
                <span className="text-slate-300">{line.text}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {report && (
        <Card className="grid grid-cols-3 gap-3 p-5">
          <Metric label="Files" value={report.files_indexed} />
          <Metric label="Chunks" value={report.chunks_indexed} />
          <Metric label="Pruned" value={report.chunks_pruned} />
        </Card>
      )}

      <Card className="p-5">
        <h3 className="mb-4 text-sm font-medium text-slate-700 dark:text-slate-200">
          Source registry
        </h3>
        {!sources && (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        )}
        {sources && sources.length === 0 && (
          <EmptyState title="No sources yet" hint="Add a path or upload files to begin." />
        )}
        {sources && sources.length > 0 && (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {sources.map((source) => (
              <div key={source.source} className="flex items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-sm text-slate-800 dark:text-slate-100">
                    {source.source}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone="neutral">{source.chunks} chunks</Badge>
                    <Badge tone={source.review.pending > 0 ? "amber" : "green"}>
                      {source.review.pending} pending
                    </Badge>
                  </div>
                </div>
                <IconButton onClick={() => setPendingDelete(source)} aria-label={`Delete ${source.source}`}>
                  <IconTrash className="h-4 w-4" />
                </IconButton>
              </div>
            ))}
          </div>
        )}
      </Card>

      {pendingDelete && (
        <Modal
          title="Delete source"
          onClose={() => setPendingDelete(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setPendingDelete(null)}>
                Cancel
              </Button>
              <Button variant="danger" onClick={deleteSource}>
                Delete
              </Button>
            </>
          }
        >
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Remove all chunks indexed from <span className="font-mono">{pendingDelete.source}</span>.
          </p>
        </Modal>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className="text-lg font-semibold text-slate-900 dark:text-white">
        {value.toLocaleString()}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run Source Intake E2E**

Run:

```bash
npm run test:e2e -- tests/source_intake.spec.ts
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Run all frontend checks**

Run:

```bash
npm run build
npm run test:e2e
```

Expected:

```text
✓ built
11 passed
```

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/SourceIntake.tsx web/tests/source_intake.spec.ts web/src/main.tsx
git commit -m "feat(web): add source intake workspace"
```

---

### Task 7: Final Wave 1 Verification And Documentation Note

**Files:**
- Modify: `docs/DEVLOG.md`
- Modify: `docs/TASKS.md`

- [ ] **Step 1: Add Wave 1 development note**

Append this section to `docs/DEVLOG.md`:

```markdown
## 2026-06-27 — Enterprise Redesign Wave 1 Start

Started implementation of the approved enterprise redesign blueprint. Wave 1
focuses on Command Center, Source Intake, readiness summary, and test harness
stability. It keeps the existing ingestion/retrieval/MCP core intact and adds
the first enterprise workflow surface around the active knowledge base.
```

- [ ] **Step 2: Add Wave 1 task entry**

Append this section to `docs/TASKS.md`:

```markdown
## Enterprise Redesign Wave 1

| # | 狀態 | Effort | 任務 | 內容 | 位置 |
|---|------|--------|------|------|------|
| E1.1 | ✅ | Low | Test harness stability | Make direct pytest launcher and Playwright mocks stable | `tests/__init__.py`, `web/tests/helpers/mockApi.ts`, `TaskCenter.tsx` |
| E1.2 | ✅ | Medium | Workspace readiness summary | Backend readiness service and `/api/workspace/readiness` | `quality/readiness.py`, `api/workspace_routes.py` |
| E1.3 | ✅ | Medium | Command Center | First-screen lifecycle/readiness workspace | `web/src/pages/CommandCenter.tsx` |
| E1.4 | ✅ | Medium | Source Intake | Consolidated intake and source registry workflow | `web/src/pages/SourceIntake.tsx` |
```

- [ ] **Step 3: Run backend verification**

Run:

```bash
.venv/bin/pytest tests/test_graph_collection_scope.py -q
.venv/bin/python -m pytest -q
```

Expected:

```text
2 passed
421+ passed, 3 skipped
```

The exact full-suite pass count may be greater than 421 after adding Wave 1 tests.

- [ ] **Step 4: Run frontend verification**

Run:

```bash
npm run build
npm run test:e2e
```

Expected:

```text
✓ built
11 passed
```

- [ ] **Step 5: Inspect changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected:

```text
Only Wave 1 files are modified or created.
```

- [ ] **Step 6: Commit**

```bash
git add docs/DEVLOG.md docs/TASKS.md
git commit -m "docs: record enterprise redesign wave 1"
```

---

## Self-Review

### Spec Coverage

This plan covers the approved blueprint's Wave 1 deliverables:

- Command Center: Task 5
- Source Intake: Task 6
- lifecycle/readiness summary: Tasks 2-3
- source health summary: Tasks 2, 5, 6
- Task Center summary integration: Tasks 1, 2, 5
- test harness stability: Task 1

Wave 2 and Wave 3 are intentionally out of scope and need separate implementation plans.

### Marker Scan

No task contains unresolved work markers or unspecified implementation steps. Every task includes concrete file paths, code snippets, commands, and expected outcomes.

### Type Consistency

The backend readiness response fields match the frontend `KnowledgeBaseReadiness` interface:

- `source_health`
- `review_health`
- `job_health`
- `graph_health`
- `next_action`
- `blockers`
- `warnings`

The E2E mock default uses the same shape as `KnowledgeBaseReadiness`.
