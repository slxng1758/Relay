"""
Embedding table – stores pgvector embeddings for all node content.
Enables hybrid graph-traversal + semantic similarity queries.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

try:
    from pgvector.sqlalchemy import Vector  # type: ignore
    VECTOR_DIM = 384  # all-MiniLM-L6-v2
    vector_type = Vector(VECTOR_DIM)
except ImportError:  # fallback if pgvector not installed yet
    from sqlalchemy import LargeBinary
    vector_type = LargeBinary()  # type: ignore


class NodeEmbedding(Base):
    """One embedding per node – re-generated when node content changes."""
    __tablename__ = "node_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(vector_type, nullable=True)
    model_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_node_embeddings_node_id_type", "node_id", "node_type", unique=True),
    )


class ChunkEmbedding(Base):
    """
    Chunked embeddings for long documents (RFCs, runbooks, Jira descriptions).
    Multiple chunks can belong to one node.
    """
    __tablename__ = "chunk_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(vector_type, nullable=True)
    model_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_chunk_embeddings_node", "node_id", "node_type"),
    )