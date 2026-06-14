"""
Read-only graph browsing API.

Lists/fetches nodes by type, traverses their edges, and runs hybrid
(semantic + keyword) search across the operational graph.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.database import Base, db_session
from app.db.models.nodes import (
    Decision,
    Document,
    NodeType,
    Person,
    Repository,
    Service,
    Task,
    Team,
)
from app.db.repositories.base import BaseRepository
from app.db.repositories.edge_repository import EdgeRepository
from app.memory.retrieval.retriever import HybridRetriever
from app.schemas import EdgeResponse, NodeResponse, SearchResponse, SearchResult

router = APIRouter()

_NODE_MODELS: dict[str, type[Base]] = {
    NodeType.TEAM: Team,
    NodeType.PERSON: Person,
    NodeType.SERVICE: Service,
    NodeType.REPOSITORY: Repository,
    NodeType.DECISION: Decision,
    NodeType.TASK: Task,
    NodeType.DOCUMENT: Document,
}

# Columns surfaced via the top-level NodeResponse fields rather than `attributes`.
_NODE_RESPONSE_COLUMNS = {"id", "external_id", "source_system", "created_at", "updated_at", "metadata"}


def _model_for(node_type: str) -> type[Base]:
    model = _NODE_MODELS.get(node_type)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Unknown node type '{node_type}'")
    return model


def _serialize_node(instance: Any, node_type: str) -> NodeResponse:
    attributes = {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
        if column.name not in _NODE_RESPONSE_COLUMNS
    }
    return NodeResponse(
        id=instance.id,
        node_type=node_type,
        source_system=instance.source_system,
        external_id=instance.external_id,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        attributes=attributes,
    )


@router.get("/nodes/{node_type}", response_model=list[NodeResponse])
async def list_nodes(node_type: str, limit: int = Query(50, le=200), offset: int = 0) -> Any:
    model = _model_for(node_type)

    async with db_session() as session:
        repo: BaseRepository[Any] = BaseRepository(session)
        repo.model = model
        instances = await repo.list(limit=limit, offset=offset)

    return [_serialize_node(instance, node_type) for instance in instances]


@router.get("/nodes/{node_type}/{node_id}", response_model=NodeResponse)
async def get_node(node_type: str, node_id: uuid.UUID) -> Any:
    model = _model_for(node_type)

    async with db_session() as session:
        repo: BaseRepository[Any] = BaseRepository(session)
        repo.model = model
        instance = await repo.get(node_id)

    if instance is None:
        raise HTTPException(status_code=404, detail=f"{node_type} {node_id} not found")

    return _serialize_node(instance, node_type)


@router.get("/nodes/{node_type}/{node_id}/edges", response_model=list[EdgeResponse])
async def get_node_edges(node_type: str, node_id: uuid.UUID) -> Any:
    _model_for(node_type)  # validates node_type, 404s if unknown

    async with db_session() as session:
        edges = await EdgeRepository(session).get_neighbours(node_id)

    return [
        EdgeResponse(
            id=edge.id,
            edge_type=edge.edge_type,
            source_id=edge.source_id,
            source_type=edge.source_type,
            target_id=edge.target_id,
            target_type=edge.target_type,
            weight=edge.weight,
            confidence=edge.confidence,
            inferred=edge.inferred,
        )
        for edge in edges
    ]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str,
    types: str = Query(..., description="Comma-separated node types to search"),
    top_k: int = Query(10, le=50),
) -> Any:
    node_types = [t.strip() for t in types.split(",") if t.strip()]

    retriever = HybridRetriever()
    results = await retriever.search(query=q, node_types=node_types, top_k=top_k)

    return SearchResponse(query=q, results=[SearchResult(**r) for r in results])
