"""
Sentence-transformer embedder for semantic search over the operational graph.

Wraps a synchronous SentenceTransformer model and runs `encode()` calls in a
thread so async callers (agents, ingestion connectors) don't block the event loop.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Embedder:
    def __init__(self, model_name: str) -> None:
        logger.info("embedder.loading", model=model_name)
        self._model = SentenceTransformer(model_name)

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = await asyncio.to_thread(self._model.encode, texts, convert_to_numpy=True)
        return [vector.tolist() for vector in embeddings]


@lru_cache
def get_embedder() -> Embedder:
    return Embedder(settings.embedding_model)
