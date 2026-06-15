"""Chroma-backed vector store.

We supply embeddings ourselves (the collection has no embedding function) so the
store stays decoupled from the embedder choice. Cosine space is used, and chunk
IDs are content hashes so re-ingesting unchanged content is an idempotent upsert.
"""

from __future__ import annotations

from typing import Optional

from ..embedding.base import Embedder
from ..models import Chunk, SearchResult


class ChromaStore:
    def __init__(
        self,
        embedder: Embedder,
        data_dir,
        collection_name: str = "domain_knowledge",
        client=None,
    ):
        import chromadb

        self._embedder = embedder
        self._collection_name = collection_name
        if client is not None:
            self._client = client
        else:
            self._client = chromadb.PersistentClient(path=str(data_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        embeddings = self._embedder.embed([c.embedding_text() for c in chunks])
        self._collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata() for c in chunks],
        )
        return len(chunks)

    def search(
        self, query: str, top_k: int = 5, where: Optional[dict] = None
    ) -> list[SearchResult]:
        qvec = self._embedder.embed([query])[0]
        res = self._collection.query(
            query_embeddings=[qvec], n_results=top_k, where=where
        )
        results: list[SearchResult] = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i, _id in enumerate(ids):
            distance = dists[i] if i < len(dists) else 0.0
            results.append(
                SearchResult(
                    id=_id,
                    text=docs[i],
                    score=round(1.0 - distance, 6),  # cosine similarity
                    metadata=metas[i] or {},
                )
            )
        return results

    def get_items(
        self, limit: int = 50, offset: int = 0, where: Optional[dict] = None
    ) -> list[dict]:
        res = self._collection.get(
            limit=limit, offset=offset, where=where,
            include=["documents", "metadatas"],
        )
        items = []
        for i, _id in enumerate(res["ids"]):
            items.append(
                {"id": _id, "text": res["documents"][i], "metadata": res["metadatas"][i] or {}}
            )
        return items

    def get_item(self, item_id: str) -> Optional[dict]:
        res = self._collection.get(ids=[item_id], include=["documents", "metadatas"])
        if not res["ids"]:
            return None
        return {
            "id": res["ids"][0],
            "text": res["documents"][0],
            "metadata": res["metadatas"][0] or {},
        }

    def update_metadata(self, item_id: str, metadata: dict) -> bool:
        if self.get_item(item_id) is None:
            return False
        self._collection.update(ids=[item_id], metadatas=[metadata])
        return True

    def delete_item(self, item_id: str) -> bool:
        if self.get_item(item_id) is None:
            return False
        self._collection.delete(ids=[item_id])
        return True

    def stats(self) -> dict:
        return {
            "collection": self._collection_name,
            "count": self._collection.count(),
            "embedder": self._embedder.name,
            "dim": self._embedder.dim,
        }

    def clear(self) -> None:
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"}
        )
