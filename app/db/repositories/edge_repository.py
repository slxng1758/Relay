"""
EdgeRepository – CRUD + graph traversal helpers for the edges table.
"""
import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.edges import Edge, EdgeType
from app.db.repositories.base import BaseRepository
from app.core.logging import get_logger

logger = get_logger(__name__)


class EdgeRepository(BaseRepository[Edge]):
    model = Edge

    # ── Write ─────────────────────────────────────────────────────────────────

    async def get_or_create_edge(
        self,
        source_id: uuid.UUID,
        source_type: str,
        target_id: uuid.UUID,
        target_type: str,
        edge_type: EdgeType,
        **kwargs: Any,
    ) -> tuple[Edge, bool]:
        result = await self.session.execute(
            select(Edge).where(
                and_(
                    Edge.source_id == source_id,
                    Edge.target_id == target_id,
                    Edge.edge_type == edge_type,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing, False
        edge = await self.create(
            source_id=source_id,
            source_type=source_type,
            target_id=target_id,
            target_type=target_type,
            edge_type=edge_type,
            **kwargs,
        )
        return edge, True

    # ── Traversal ─────────────────────────────────────────────────────────────

    async def get_outgoing(
        self, node_id: uuid.UUID, edge_type: EdgeType | None = None
    ) -> list[Edge]:
        q = select(Edge).where(Edge.source_id == node_id)
        if edge_type:
            q = q.where(Edge.edge_type == edge_type)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_incoming(
        self, node_id: uuid.UUID, edge_type: EdgeType | None = None
    ) -> list[Edge]:
        q = select(Edge).where(Edge.target_id == node_id)
        if edge_type:
            q = q.where(Edge.edge_type == edge_type)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_neighbours(self, node_id: uuid.UUID) -> list[Edge]:
        result = await self.session.execute(
            select(Edge).where(
                (Edge.source_id == node_id) | (Edge.target_id == node_id)
            )
        )
        return list(result.scalars().all())

    async def dependency_chain(
        self, service_id: uuid.UUID, depth: int = 3
    ) -> list[dict[str, Any]]:
        """
        Recursive CTE traversal for DEPENDS_ON chains.
        Returns list of {source_id, target_id, depth} dicts.
        """
        sql = """
            WITH RECURSIVE dep_chain AS (
                SELECT source_id, target_id, 1 AS depth
                FROM edges
                WHERE source_id = :root_id AND edge_type = 'depends_on'
                UNION ALL
                SELECT e.source_id, e.target_id, dc.depth + 1
                FROM edges e
                JOIN dep_chain dc ON e.source_id = dc.target_id
                WHERE e.edge_type = 'depends_on' AND dc.depth < :max_depth
            )
            SELECT DISTINCT source_id, target_id, depth FROM dep_chain;
        """
        from sqlalchemy import text

        result = await self.session.execute(
            text(sql), {"root_id": str(service_id), "max_depth": depth}
        )
        return [dict(row._mapping) for row in result]