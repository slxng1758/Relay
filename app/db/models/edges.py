"""
Graph edge models – typed relationships between any two nodes.
Uses a polymorphic adjacency table pattern so edges can connect any node types.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EdgeType(StrEnum):
    # Ownership
    OWNS = "owns"                        # Team/Person → Service/Repo
    MAINTAINS = "maintains"              # Person → Service
    MEMBER_OF = "member_of"              # Person → Team

    # Work dependencies
    DEPENDS_ON = "depends_on"            # Service/Task → Service/Task
    BLOCKS = "blocks"                    # Task → Task
    RELATED_TO = "related_to"            # any → any

    # Decision lineage
    INFORMED_BY = "informed_by"          # Decision → Document/Task
    SUPERSEDES = "supersedes"            # Decision → Decision
    AUTHORED = "authored"                # Person → Decision/Document

    # Risk
    RISKS = "risks"                      # any → any (risk signal)

    # Documentation
    REFERENCES = "references"            # Document → any
    DOCUMENTS = "documents"              # Document → Service/Task


class Edge(Base):
    """
    Universal directed edge between two graph nodes.
    source_id / target_id reference rows in *any* node table (stored as UUID).
    node_type columns carry the table name so queries can JOIN correctly.
    """
    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)  # NodeType value

    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)

    weight: Mapped[float] = mapped_column(default=1.0)
    confidence: Mapped[float] = mapped_column(default=1.0)  # 0–1, agent-assigned
    inferred: Mapped[bool] = mapped_column(default=False)   # True = agent-derived

    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source_system: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_edges_source", "source_id", "source_type"),
        Index("ix_edges_target", "target_id", "target_type"),
        Index("ix_edges_type_source", "edge_type", "source_id"),
    )