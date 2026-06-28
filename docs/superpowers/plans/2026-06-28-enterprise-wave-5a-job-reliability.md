# Enterprise Wave 5A Job Reliability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing Task Center and background task domain into an explicit, recoverable job contract with structured failure evidence and retry support.

**Architecture:** Keep the current in-process worker and file-backed `TaskStore`. Add validated job status constants, transition helpers, recovery metadata, structured error fields, a retry route, and focused Task Center controls.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, React, TypeScript, Vite, Playwright.

---

## File Map

- Modify `src/opendomainmcp/tasks/models.py`: add job status constants, retryable status sets, new task fields, and load-time status validation.
- Modify `src/opendomainmcp/tasks/store.py`: add validated transitions, recovery, retry cloning, and status-aware updates.
- Modify `src/opendomainmcp/tasks/worker.py`: use transitions, increment attempts, record recovery and structured failure evidence.
- Modify `src/opendomainmcp/api/task_routes.py`: add `POST /api/tasks/{task_id}/retry`.
- Modify `tests/test_task_store.py`: cover status validation, transition metadata, recovery metadata, and retry cloning.
- Modify `tests/test_task_worker.py`: cover attempts, structured errors, cancellation result, and recovery.
- Modify `tests/test_task_api.py`: cover retry success, 404, and 409 cases.
- Modify `web/src/api.ts`: add new task fields and `retryTask`.
- Modify `web/src/components/TaskCenter.tsx`: render failure/recovery evidence and retry action.
- Modify `web/tests/helpers/mockApi.ts`: support retry endpoint and enriched task rows.
- Modify `web/tests/smoke.spec.ts`: verify Task Center retry and failure/recovery display.
- Modify `docs/DEVLOG.md`, `docs/TASKS.md`: record Wave 5A completion and verification.

## Task 1: Job Model And Store Contract

**Files:**
- Modify: `src/opendomainmcp/tasks/models.py`
- Modify: `src/opendomainmcp/tasks/store.py`
- Test: `tests/test_task_store.py`

- [ ] **Step 1: Write failing store tests**

Add focused tests for:

- persisted task rows with an unknown `status` fail loudly on store load;
- `TaskStore.transition()` validates statuses, records `last_transition`, and sets `finished_at` for terminal states;
- `TaskStore.mark_recovered()` converts `running` to `queued`, increments `recovery_count`, sets `recovered_at`, clears `cancel_requested`, and records `last_transition`;
- `TaskStore.retry()` creates a new queued task with copied type/title/collection/params and a `result.retry_of` reference to the original task.

Run and confirm the new tests fail:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_store.py -q
```

- [ ] **Step 2: Implement model constants and validated store behavior**

In `tasks/models.py`:

- define `JOB_QUEUED`, `JOB_RUNNING`, `JOB_DONE`, `JOB_ERROR`, `JOB_CANCELLED`;
- define `JOB_STATUSES`, `ACTIVE_STATUSES`, `TERMINAL_STATUSES`, `RETRYABLE_TERMINAL_STATUSES`;
- add task fields `attempts`, `recovered_at`, `recovery_count`, `last_transition`, `error_type`, `error_message`;
- validate status in `Task.from_dict()`.

In `tasks/store.py`:

- centralize status validation;
- keep `update()` backwards compatible while validating status updates;
- add `transition(task_id, status, **fields)`;
- add `mark_recovered(task_id)`;
- add `retry(task_id)`.

- [ ] **Step 3: Verify store scope**

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_store.py -q
```

Commit after green:

```bash
git add src/opendomainmcp/tasks/models.py src/opendomainmcp/tasks/store.py tests/test_task_store.py
git commit -m "feat: add validated job store contract"
```

## Task 2: Worker Recovery And Failure Evidence

**Files:**
- Modify: `src/opendomainmcp/tasks/worker.py`
- Test: `tests/test_task_worker.py`

- [ ] **Step 1: Write failing worker tests**

Add focused tests for:

- `recover()` marks stale `running` tasks as recovered rather than raw-updating them;
- task start increments `attempts`;
- runner exceptions persist `error_type`, `error_message`, and backwards-compatible `error`;
- cancelled tasks finish with a clear cancellation result summary.

Run and confirm the new tests fail:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_worker.py -q
```

- [ ] **Step 2: Implement worker transitions**

Update worker execution to:

- call `store.mark_recovered()` in `recover()`;
- transition tasks to `running` with incremented attempts;
- transition to `done`, `cancelled`, or `error` through `store.transition()`;
- store structured exception evidence without crashing the worker loop.

- [ ] **Step 3: Verify worker scope**

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_worker.py -q
```

Commit after green:

```bash
git add src/opendomainmcp/tasks/worker.py tests/test_task_worker.py
git commit -m "feat: record job recovery and failure evidence"
```

## Task 3: Retry API

**Files:**
- Modify: `src/opendomainmcp/api/task_routes.py`
- Test: `tests/test_task_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- retrying an `error` task returns a new queued task and wakes the worker;
- retrying an unknown task returns `404`;
- retrying a non-retryable task returns `409`.

Run and confirm the new tests fail:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_api.py -q
```

- [ ] **Step 2: Implement retry route**

Add `POST /api/tasks/{task_id}/retry` to `register_task_routes()`. The route should call `TaskStore.retry()`, translate unknown ids to `404`, translate non-retryable states to `409`, wake the worker after success, and return the new task row.

- [ ] **Step 3: Verify API scope**

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_api.py -q
```

Commit after green:

```bash
git add src/opendomainmcp/api/task_routes.py tests/test_task_api.py
git commit -m "feat: expose task retry endpoint"
```

## Task 4: Task Center Retry UX

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/components/TaskCenter.tsx`
- Modify: `web/tests/helpers/mockApi.ts`
- Modify: `web/tests/smoke.spec.ts`

- [ ] **Step 1: Write failing frontend test**

Add a smoke test that opens Task Center and verifies:

- a failed task shows structured failure text;
- a recovered task shows recovery evidence;
- retrying a failed task posts to `/api/tasks/{id}/retry`;
- active jobs still show cancel.

Run and confirm the new frontend test fails:

```bash
cd web
npm run test:e2e -- tests/smoke.spec.ts
```

- [ ] **Step 2: Implement UI and client support**

Update `api.ts` task types with the new backend fields and add `retryTask(taskId)`.

Update `TaskCenter.tsx` to:

- show `error_type` and `error_message` when present, falling back to `error`;
- show a compact recovered indicator when `recovery_count > 0`;
- show a `Retry` button for `error` and `cancelled`;
- leave `Cancel` and `Clear finished` behavior intact.

- [ ] **Step 3: Verify frontend scope**

```bash
cd web
npm run test:e2e -- tests/smoke.spec.ts
```

Commit after green:

```bash
git add web/src/api.ts web/src/components/TaskCenter.tsx web/tests/helpers/mockApi.ts web/tests/smoke.spec.ts
git commit -m "feat: add task retry controls"
```

## Task 5: Documentation, Regression, PR, Merge, Deploy

**Files:**
- Modify: `docs/DEVLOG.md`
- Modify: `docs/TASKS.md`
- Generated: `docs/public/*` if `docs/build.py` changes docs output.

- [ ] **Step 1: Update docs**

Record Wave 5A behavior, tests, and operator impact in `docs/DEVLOG.md` and `docs/TASKS.md`.

Run docs build if present:

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python docs/build.py
```

- [ ] **Step 2: Run focused regression**

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest tests/test_task_store.py tests/test_task_worker.py tests/test_task_api.py tests/test_workspace_readiness.py::test_workspace_readiness_uses_app_task_store_and_filters_collection -q
cd web
npm run test:e2e -- tests/source_intake.spec.ts tests/smoke.spec.ts
```

- [ ] **Step 3: Run full verification**

```bash
PYTHONPATH=src /Users/b5336789/Documents/workspace/open-domain-mcp/.venv/bin/python -m pytest -q
cd web
npm run build
npm run test:e2e
```

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` after verification and address findings before PR.

- [ ] **Step 5: Publish, merge, and redeploy locally**

Create a PR for `enterprise-wave-5a-job-reliability`, merge after checks/review, return to `main`, pull the merge commit, and restart the local demo server at `http://127.0.0.1:8000` with the merged code.
