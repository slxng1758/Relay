"""
Common interface for ingestion connectors.

Each connector pulls data from one external source (Slack, GitHub, Jira, GDocs),
upserts the corresponding graph nodes/edges, and reports back an `IngestionStats`
summary. Shared upsert helpers go through the existing repository pattern so
connectors don't duplicate get-or-create logic.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import SourceSystem
from app.db.repositories.base import BaseRepository
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


@dataclass
class IngestionStats:
    """Summary of a connector sync/event run, returned for logging and webhook responses."""

    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "IngestionStats") -> "IngestionStats":
        self.nodes_created += other.nodes_created
        self.nodes_updated += other.nodes_updated
        self.edges_created += other.edges_created
        self.errors.extend(other.errors)
        return self


class BaseConnector(ABC):
    """Base class for source-specific ingestion connectors."""

    source_system: SourceSystem

    @abstractmethod
    async def sync(self, full_sync: bool = False) -> IngestionStats:
        """Pull data from the external source and upsert it into the graph."""

    async def handle_event(self, *args: Any, **kwargs: Any) -> IngestionStats:
        """Handle a single real-time webhook event. Connectors that support
        webhooks override this; the default is a no-op."""
        return IngestionStats()

    # ── Shared upsert helpers ────────────────────────────────────────────────

    async def get_node(
        self, session: AsyncSession, model: type[Base], external_id: str
    ) -> Any | None:
        """Look up a node of `model` by (external_id, this connector's source_system)."""
        repo: BaseRepository[Any] = BaseRepository(session)
        repo.model = model
        return await repo.get_by_external_id(external_id, str(self.source_system))

    async def upsert_node(
        self,
        session: AsyncSession,
        model: type[Base],
        external_id: str,
        **fields: Any,
    ) -> tuple[Any, bool]:
        """Insert or update a node of `model`, keyed on (external_id, source_system)."""
        repo: BaseRepository[Any] = BaseRepository(session)
        repo.model = model
        return await repo.upsert_by_external_id(external_id, str(self.source_system), **fields)

    async def upsert_edge(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        source_type: str,
        target_id: uuid.UUID,
        target_type: str,
        edge_type: EdgeType,
        **fields: Any,
    ) -> tuple[Any, bool]:
        """Get-or-create an edge, stamped with this connector's source_system."""
        repo = EdgeRepository(session)
        return await repo.get_or_create_edge(
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type,
            edge_type=edge_type,
            source_system=str(self.source_system),
            **fields,
        )
