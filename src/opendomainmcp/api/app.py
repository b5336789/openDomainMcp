"""FastAPI layer for the web dashboard.

A thin HTTP wrapper over the shared :class:`~opendomainmcp.context.Context`
(pipeline + store). No business logic lives here. Ingestion progress is streamed
to the browser via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..config import get_settings
from ..context import Context, build_context

STATIC_DIR = Path(__file__).parent / "static"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    kind: str | None = None
    language: str | None = None
    symbol: str | None = None
    source_contains: str | None = None


class ItemPatch(BaseModel):
    metadata: dict


class SettingsPatch(BaseModel):
    values: dict


def create_app(context: Context | None = None, context_factory=build_context) -> FastAPI:
    app = FastAPI(title="openDomainMcp")
    app.state.context = context
    app.state.context_factory = context_factory

    def get_ctx() -> Context:
        if app.state.context is None:
            app.state.context = app.state.context_factory()
        return app.state.context

    # -- status & search ------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/stats")
    def stats(ctx: Context = Depends(get_ctx)):
        data = ctx.store.stats()
        data["data_dir"] = str(ctx.settings.data_dir)
        data["extract_knowledge"] = ctx.settings.extract_knowledge
        return data

    @app.post("/api/search")
    def search(req: SearchRequest, ctx: Context = Depends(get_ctx)):
        from ..store import build_where

        where = build_where({"kind": req.kind, "language": req.language, "symbol": req.symbol})
        results = ctx.store.search(
            req.query, top_k=req.top_k, where=where,
            mode=ctx.settings.search_mode, source_contains=req.source_contains,
        )
        return [r.to_dict() for r in results]

    # -- ingestion ------------------------------------------------------
    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...), ctx: Context = Depends(get_ctx)):
        stage = ctx.settings.data_dir / "uploads" / uuid.uuid4().hex
        stage.mkdir(parents=True, exist_ok=True)
        names = []
        for f in files:
            dest = stage / Path(f.filename or "upload").name
            dest.write_bytes(await f.read())
            names.append(dest.name)
        return {"path": str(stage), "files": names}

    @app.get("/api/ingest/stream")
    async def ingest_stream(path: str, sync: bool = False, ctx: Context = Depends(get_ctx)):
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def progress(event):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run():
            try:
                report = await asyncio.to_thread(
                    ctx.pipeline.ingest_path, path, progress, sync
                )
                queue.put_nowait({"stage": "report", **report.to_dict()})
            except Exception as exc:  # surface failures to the UI (Fail Loud)
                queue.put_nowait({"stage": "error", "path": path, "detail": repr(exc)})
            queue.put_nowait(None)

        async def events():
            task = asyncio.create_task(run())
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield {"event": event["stage"], "data": json.dumps(event)}
            finally:
                await task

        return EventSourceResponse(events())

    # -- browse & edit --------------------------------------------------
    @app.get("/api/items")
    def list_items(limit: int = 50, offset: int = 0, kind: str | None = None,
                   ctx: Context = Depends(get_ctx)):
        where = {"kind": kind} if kind else None
        return ctx.store.get_items(limit=limit, offset=offset, where=where)

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str, ctx: Context = Depends(get_ctx)):
        item = ctx.store.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        return item

    @app.patch("/api/items/{item_id}")
    def update_item(item_id: str, patch: ItemPatch, ctx: Context = Depends(get_ctx)):
        if not ctx.store.update_metadata(item_id, patch.metadata):
            raise HTTPException(status_code=404, detail="item not found")
        return ctx.store.get_item(item_id)

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: str, ctx: Context = Depends(get_ctx)):
        if not ctx.store.delete_item(item_id):
            raise HTTPException(status_code=404, detail="item not found")
        return {"deleted": item_id}

    # -- settings -------------------------------------------------------
    @app.get("/api/settings")
    def read_settings(ctx: Context = Depends(get_ctx)):
        return {
            "editable": ctx.settings.editable_dict(),
            "collection": ctx.settings.collection_name,
            "embedder_backend": ctx.settings.embedder_backend,
            "data_dir": str(ctx.settings.data_dir),
        }

    @app.patch("/api/settings")
    def patch_settings(patch: SettingsPatch, ctx: Context = Depends(get_ctx)):
        try:
            ctx.settings.save_overrides(patch.values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Force a rebuild so later requests pick up the new settings.
        app.state.context = None
        return JSONResponse({"updated": list(patch.values)})

    # -- static SPA (built frontend), if present ------------------------
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()


def main() -> None:
    import os

    import uvicorn

    host = os.environ.get("ODM_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("ODM_WEB_PORT", "8000"))
    uvicorn.run("opendomainmcp.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
