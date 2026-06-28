from __future__ import annotations

from fastapi import HTTPException

from ..context import Context
from ..views import VIEWS, run_view_tool


def unique_simulation_results(simulation: dict) -> list[dict]:
    """Return de-duplicated result rows across every simulated tool call."""
    results, seen = [], set()
    for tool in simulation.get("tools") or []:
        for result in tool.get("results") or []:
            result_id = result.get("id")
            if result_id not in seen:
                seen.add(result_id)
                results.append(result)
    return results


def run_simulation(ctx: Context, view: str, query: str, top_k: int = 5) -> dict:
    spec = VIEWS.get(view)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown view {view!r}")

    tools_out = []
    for tool in spec.tools:
        results = run_view_tool(ctx, tool, query, top_k)
        tools_out.append({"tool": tool.name, "results": results})

    all_results = unique_simulation_results({"tools": tools_out})
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
