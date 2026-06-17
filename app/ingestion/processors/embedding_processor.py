"""
Generates and upserts NodeEmbedding rows for ingested nodes so they become
searchable via HybridRetriever.
"""
from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    vector = await get_embedder().embed_text(text)

    stmt = (
        pg_insert(NodeEmbedding)
        .values(
            node_id=node_id,
            node_type=node_type,
            text_content=text,
            embedding=vector,
            model_name=settings.embedding_model,
        )
        .on_conflict_do_update(
            index_elements=["node_id", "node_type"],
            set_=dict(
                text_content=text,
                embedding=vector,
                model_name=settings.embedding_model,
            ),
        )
    )
    await session.execute(stmt)
    await session.flush()
    logger.debug("embedding_processor.embedded", node_id=str(node_id), node_type=node_type)
