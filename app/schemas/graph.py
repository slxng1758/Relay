"""Request/response schemas for app/api/routes/graph.py (read-only graph browsing)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NodeResponse(BaseModel):
    id: uuid.UUID
    node_type: str
    source_system: str
    external_id: str | None = None
    created_at: datetime
    updated_at: datetime
    attributes: dict[str, Any]


class EdgeResponse(BaseModel):
    id: uuid.UUID
    edge_type: str
    source_id: uuid.UUID
    source_type: str
    target_id: uuid.UUID
    target_type: str
    weight: float
    confidence: float
    inferred: bool


class SearchResult(BaseModel):
    node_id: uuid.UUID
    node_type: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
