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
