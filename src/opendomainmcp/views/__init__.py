"""Declarative MCP view definitions.

A "view" is a role-specific MCP server (Product / Operations / Developer /
Support / Architecture). Each view exposes a handful of typed tools, but every
tool is just a filtered search over the *same* knowledge store -- so we describe
them as data (tool name + filters) and let ``server.build_view_server`` turn each
entry into a real MCP tool. This keeps the 20+ tools as thin wrappers rather than
hand-written functions.

``filters`` keys map onto :func:`opendomainmcp.store.build_where` (``kind``,
``language``, ``knowledge_type`` ...). The special key ``audience`` is not a
Chroma filter (a chunk may serve several audiences and is stored as a joined
string); it is post-filtered after retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ViewTool:
    name: str
    description: str
    filters: dict = field(default_factory=dict)
    default_top_k: int = 5


@dataclass(frozen=True)
class ViewSpec:
    name: str
    title: str
    purpose: str
    tools: tuple[ViewTool, ...]


VIEWS: dict[str, ViewSpec] = {
    "product": ViewSpec(
        name="product",
        title="Product MCP",
        purpose="Product usage understanding",
        tools=(
            ViewTool("get_feature", "Find product features matching the query.",
                     {"knowledge_type": "Feature"}),
            ViewTool("get_workflow", "Find product workflows or usage flows.",
                     {"knowledge_type": "Workflow"}),
            ViewTool("get_constraint", "Find product constraints and limitations.",
                     {"knowledge_type": "Constraint"}),
            ViewTool("search_product_knowledge",
                     "Search all product-manager-facing knowledge.",
                     {"audience": "product_manager"}),
        ),
    ),
    "operations": ViewSpec(
        name="operations",
        title="Operations MCP",
        purpose="Execution guidance",
        tools=(
            ViewTool("get_runbook", "Find runbooks for an operational task.",
                     {"knowledge_type": "Runbook"}),
            ViewTool("get_troubleshooting", "Find troubleshooting guidance.",
                     {"knowledge_type": "Troubleshooting"}),
            ViewTool("get_incident_response",
                     "Find incident-response procedures.",
                     {"knowledge_type": "Runbook", "audience": "operations"}),
            ViewTool("get_rollback_procedure",
                     "Find rollback or recovery procedures.",
                     {"knowledge_type": "Runbook"}),
        ),
    ),
    "developer": ViewSpec(
        name="developer",
        title="Developer MCP",
        purpose="Code understanding",
        tools=(
            ViewTool("search_code", "Search source code by intent or symbol.",
                     {"kind": "code"}),
            ViewTool("get_class", "Find a class or type definition.",
                     {"kind": "code"}),
            ViewTool("get_function", "Find a function or method definition.",
                     {"kind": "code"}),
            ViewTool("trace_dependency",
                     "Find code and relations describing dependencies.",
                     {"kind": "code"}),
            ViewTool("get_api_implementation",
                     "Find the code or spec behind an API.",
                     {"knowledge_type": "API"}),
        ),
    ),
    "support": ViewSpec(
        name="support",
        title="Support MCP",
        purpose="Customer support",
        tools=(
            ViewTool("get_known_issue", "Find known issues and errors.",
                     {"knowledge_type": "Error"}),
            ViewTool("get_error_explanation", "Explain an error or message.",
                     {"knowledge_type": "Error"}),
            ViewTool("get_resolution_steps",
                     "Find resolution and troubleshooting steps.",
                     {"knowledge_type": "Troubleshooting"}),
            ViewTool("search_faq", "Search frequently asked questions.",
                     {"knowledge_type": "FAQ"}),
        ),
    ),
    "architecture": ViewSpec(
        name="architecture",
        title="Architecture MCP",
        purpose="System understanding",
        tools=(
            ViewTool("get_component", "Find architectural components.",
                     {"knowledge_type": "Architecture"}),
            ViewTool("get_dependency",
                     "Find dependencies between components.",
                     {"knowledge_type": "Architecture"}),
            ViewTool("get_dataflow", "Find data flows through the system.",
                     {"knowledge_type": "Architecture"}),
            ViewTool("search_architecture",
                     "Search all architect-facing knowledge.",
                     {"audience": "solutions_architect"}),
        ),
    ),
}

VIEW_NAMES = tuple(VIEWS.keys())


def run_view_tool(ctx, tool: ViewTool, query: str, top_k: int) -> list[dict]:
    """Execute a view tool: a filtered search over the shared store.

    ``audience`` filters are applied client-side (see module docstring). When the
    ``retrieve_approved_only`` setting is on, results are restricted to approved
    knowledge; chunks predating the review fields have no ``review_status`` and
    are intentionally excluded only when that setting is enabled.
    """
    from ..store import build_where

    filters = dict(tool.filters)
    audience = filters.pop("audience", None)
    if getattr(ctx.settings, "retrieve_approved_only", False):
        filters["review_status"] = "approved"
    where = build_where(filters)
    # Over-fetch when we still have to post-filter by audience.
    fetch_k = top_k * 3 if audience else top_k
    results = ctx.store.search(
        query, top_k=fetch_k, where=where, mode=ctx.settings.search_mode
    )
    if audience:
        results = [
            r for r in results
            if audience in (r.metadata.get("audience") or "").split(", ")
        ][:top_k]
    return [r.to_dict() for r in results]
