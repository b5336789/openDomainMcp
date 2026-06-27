from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..context import Context
from ..quality import compute_readiness
from ..tasks.store import TaskStore
from .deps import get_ctx

router = APIRouter()


@router.get("/api/workspace/readiness")
def workspace_readiness(request: Request, ctx: Context = Depends(get_ctx)) -> dict:
    return compute_readiness(ctx, tasks=_task_rows(ctx, request.app.state))


def _task_rows(ctx: Context, app_state=None) -> list[dict]:
    store = getattr(app_state, "task_store", None) if app_state is not None else None
    if store is None:
        store = TaskStore(ctx.settings.data_dir)
    collection = ctx.store.stats().get("collection")
    rows: list[dict] = []
    for task in store.list():
        row = task.to_dict()
        if row.get("collection") == collection:
            rows.append(row)
    return rows
