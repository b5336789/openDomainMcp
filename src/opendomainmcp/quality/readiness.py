from __future__ import annotations

from collections import Counter

from ..context import Context


def compute_readiness(ctx: Context, tasks: list[dict] | None = None) -> dict:
    stats = ctx.store.stats()
    total = int(stats.get("count") or 0)
    items = ctx.store.get_items(limit=max(total, 1)) if total else []
    sources = ctx.store.list_sources()
    review = Counter((item.get("metadata") or {}).get("review_status") or "unset"
                     for item in items)
    jobs = Counter((task or {}).get("status") or "unknown" for task in (tasks or []))

    approved = review["approved"]
    pending = review["pending"]
    approved_ratio = round(approved / total, 4) if total else 0
    blockers: list[str] = []
    warnings: list[str] = []

    if total == 0:
        blockers.append("No indexed knowledge objects.")
    if jobs["error"]:
        blockers.append(_count_text(jobs["error"], "background job failed"))
    if pending:
        warnings.append(_count_text(pending, "knowledge object is pending review"))

    if blockers:
        status = "blocked"
    elif warnings:
        status = "needs_review"
    else:
        status = "ready"

    return {
        "collection": stats.get("collection"),
        "status": status,
        "score": 0 if blockers else round(approved_ratio * 100),
        "approved_ratio": approved_ratio,
        "blockers": blockers,
        "warnings": warnings,
        "next_action": _next_action(status, blockers),
        "source_health": {
            "sources": len(sources),
            "chunks": total,
        },
        "review_health": {
            "approved": approved,
            "pending": pending,
            "rejected": review["rejected"],
            "unset": review["unset"],
        },
        "job_health": dict(sorted(jobs.items())),
    }


def _count_text(count: int, singular: str) -> str:
    if count == 1:
        return f"1 {singular}."
    if singular.endswith("is pending review"):
        return f"{count} knowledge objects are pending review."
    return f"{count} {singular}s."


def _next_action(status: str, blockers: list[str]) -> str:
    if "No indexed knowledge objects." in blockers:
        return "Add sources in Source Intake."
    if "blocked" == status:
        return "Inspect failed background jobs."
    if "needs_review" == status:
        return "Review pending knowledge objects."
    return "Workspace is ready."
