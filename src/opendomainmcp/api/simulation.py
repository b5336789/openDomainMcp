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
