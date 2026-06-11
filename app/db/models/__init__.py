"""Import all models so SQLAlchemy registers them before Alembic autogenerate."""
from app.db.models.nodes import (  # noqa: F401
    Decision,
    Document,
    NodeType,
    Person,
    Repository,
    Service,
    SourceSystem,
    Task,
    Team,
)
from app.db.models.edges import Edge, EdgeType  # noqa: F401
from app.db.models.embeddings import ChunkEmbedding, NodeEmbedding  # noqa: F401

__all__ = [
    "Team", "Person", "Service", "Repository", "Decision", "Task", "Document",
    "Edge", "EdgeType", "NodeType", "SourceSystem",
    "NodeEmbedding", "ChunkEmbedding",
]