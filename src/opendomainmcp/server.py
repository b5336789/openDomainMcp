"""MCP server exposing the domain knowledge base over stdio.

Tools: ingest_path, search_knowledge, get_stats. All share the same runtime
context (pipeline/store) as the CLI and web API.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .context import build_context

mcp = FastMCP("opendomainmcp")
_ctx = None


def _context():
    global _ctx
    if _ctx is None:
        _ctx = build_context()
    return _ctx


@mcp.tool()
def ingest_path(path: str, sync: bool = False) -> dict:
    """Ingest a file or directory: extract domain knowledge and index it.

    With ``sync=True`` on a directory, chunks for files deleted under it are
    pruned. Returns counts of indexed/pruned chunks plus any skipped or errors.
    """
    return _context().pipeline.ingest_path(path, sync=sync).to_dict()


@mcp.tool()
def search_knowledge(
    query: str,
    top_k: int = 5,
    kind: Optional[str] = None,
    language: Optional[str] = None,
    symbol: Optional[str] = None,
) -> list[dict]:
    """Search the knowledge base (hybrid dense + BM25 by default).

    Optional filters: ``kind`` ('code'/'text'), ``language``, exact ``symbol``.
    """
    from .store import build_where

    ctx = _context()
    where = build_where({"kind": kind, "language": language, "symbol": symbol})
    results = ctx.store.search(query, top_k=top_k, where=where, mode=ctx.settings.search_mode)
    return [r.to_dict() for r in results]


@mcp.tool()
def get_stats() -> dict:
    """Return collection statistics (document count, embedder, dimension)."""
    return _context().store.stats()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
