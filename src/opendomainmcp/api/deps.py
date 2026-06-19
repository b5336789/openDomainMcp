"""Shared FastAPI dependencies.

The context resolver lives here (rather than inside ``create_app``) so feature
routers in their own modules can depend on the same per-collection context cache
held on ``app.state``. Behaviour is unchanged from the original inline closure:

* a pinned ``app.state.context`` (used by tests / single-collection use) wins;
* otherwise the collection is taken from the ``collection`` query param, the
  ``X-Collection`` header, or the default, and contexts are cached per name.
"""

from __future__ import annotations

from fastapi import Request

from ..config import get_settings
from ..context import Context


def get_ctx(request: Request) -> Context:
    state = request.app.state
    if getattr(state, "context", None) is not None:
        return state.context
    name = (
        request.query_params.get("collection")
        or request.headers.get("x-collection")
        or get_settings().collection_name
    )
    if name not in state.contexts:
        state.contexts[name] = state.context_factory(collection=name)
    return state.contexts[name]
