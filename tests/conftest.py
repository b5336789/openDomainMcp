"""Shared offline test fixtures.

FakeEmbedder produces deterministic vectors via a hashing bag-of-words, so token
overlap drives cosine similarity. This lets retrieval tests run with no network
and no model download.
"""

import math

import pytest

from opendomainmcp.embedding.base import Embedder

_DIM = 64


class FakeEmbedder(Embedder):
    name = "fake"

    def embed(self, texts):
        vectors = []
        for text in texts:
            vec = [0.0] * _DIM
            for token in text.lower().split():
                vec[hash(token) % _DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    @property
    def dim(self):
        return _DIM


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def store(fake_embedder):
    import chromadb

    from opendomainmcp.store import ChromaStore

    client = chromadb.EphemeralClient()
    return ChromaStore(fake_embedder, data_dir=None, client=client)
