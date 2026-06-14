"""
Generates and upserts NodeEmbedding rows for ingested nodes so they become
searchable via HybridRetriever.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.embeddings import NodeEmbedding
from app.memory.vector.embedder import get_embedder

logger = get_logger(__name__)


async def embed_node(session: AsyncSession, node_id: uuid.UUID, node_type: str, text: str) -> None:
    """Embed `text` and upsert the NodeEmbedding row for (node_id, node_type)."""
    if not text.strip():
        return

    embedder = get_embedder()
    vector = await embedder.embed_text(text)

    result = await session.execute(
        select(NodeEmbedding).where(
            NodeEmbedding.node_id == node_id, NodeEmbedding.node_type == node_type
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.text_content = text
        existing.embedding = vector
        existing.model_name = settings.embedding_model
    else:
        session.add(
            NodeEmbedding(
                node_id=node_id,
                node_type=node_type,
                text_content=text,
                embedding=vector,
                model_name=settings.embedding_model,
            )
        )

    await session.flush()
    logger.debug("embedding_processor.embedded", node_id=str(node_id), node_type=node_type)
