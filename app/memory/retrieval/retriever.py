"""
Hybrid retriever used by agents (e.g. the decision agent) to find candidate nodes.

Tries pgvector cosine-similarity search over `NodeEmbedding` first; if nothing
clears `settings.vector_similarity_threshold`, falls back to an ILIKE keyword
search over the relevant node tables.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.db.models.embeddings import NodeEmbedding
from app.db.models.nodes import Decision, Document, Person, Repository, Service, Task, Team

logger = get_logger(__name__)

# node_type -> (model, [columns to keyword-search])
_KEYWORD_SEARCH_TARGETS: dict[str, tuple[Any, list[str]]] = {
    "decision": (Decision, ["title", "summary"]),
    "task": (Task, ["title", "description"]),
    "document": (Document, ["title"]),
    "service": (Service, ["name", "description"]),
    "repository": (Repository, ["full_name", "description"]),
    "team": (Team, ["name", "description"]),
    "person": (Person, ["display_name", "email"]),
}

# Fixed relevance score assigned to keyword-fallback matches (no real similarity metric)
_KEYWORD_MATCH_SCORE = 0.5


class HybridRetriever:
    """Semantic + keyword search across graph nodes."""

    async def search(
        self, query: str, node_types: list[str], top_k: int | None = None
    ) -> list[dict[str, Any]]:
        top_k = top_k or settings.vector_top_k

        results = await self._semantic_search(query, node_types, top_k)
        if results:
            return results

        return await self._keyword_search(query, node_types, top_k)

    async def _semantic_search(
        self, query: str, node_types: list[str], top_k: int
    ) -> list[dict[str, Any]]:
        from app.memory.vector.embedder import get_embedder

        embedder = get_embedder()
        vector = await embedder.embed_text(query)

        async with db_session() as session:
            distance = NodeEmbedding.embedding.cosine_distance(vector)
            stmt = (
                select(NodeEmbedding.node_id, NodeEmbedding.node_type, distance.label("distance"))
                .where(NodeEmbedding.node_type.in_(node_types))
                .order_by(distance)
                .limit(top_k)
            )
            rows = await session.execute(stmt)

            results = []
            for node_id, node_type, dist in rows:
                score = 1 - dist
                if score < settings.vector_similarity_threshold:
                    continue
                results.append(
                    {"node_id": str(node_id), "node_type": node_type, "score": round(score, 4)}
                )

        logger.debug("retriever.semantic_search", query=query, hits=len(results))
        return results

    async def _keyword_search(
        self, query: str, node_types: list[str], top_k: int
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        results: list[dict[str, Any]] = []

        async with db_session() as session:
            for node_type in node_types:
                target = _KEYWORD_SEARCH_TARGETS.get(node_type)
                if not target:
                    continue
                model, columns = target

                conditions = [getattr(model, col).ilike(pattern) for col in columns]
                stmt = select(model.id).where(or_(*conditions)).limit(top_k)
                rows = await session.execute(stmt)

                results.extend(
                    {"node_id": str(row[0]), "node_type": node_type, "score": _KEYWORD_MATCH_SCORE}
                    for row in rows
                )

        logger.debug("retriever.keyword_search", query=query, hits=len(results))
        return results[:top_k]
