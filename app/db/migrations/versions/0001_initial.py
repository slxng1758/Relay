"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2


def _node_columns() -> list[sa.Column]:
    """Common columns shared by every node table (mirrors NodeMixin)."""
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Teams ────────────────────────────────────────────────────────────────
    op.create_table(
        "teams",
        *_node_columns(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slack_channel_id", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_teams_external_id", "teams", ["external_id"])
    op.create_index("ix_teams_name", "teams", ["name"])

    # ── Persons ──────────────────────────────────────────────────────────────
    op.create_table(
        "persons",
        *_node_columns(),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("slack_user_id", sa.String(128), nullable=True),
        sa.Column("github_login", sa.String(128), nullable=True),
        sa.Column("jira_account_id", sa.String(128), nullable=True),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_persons_external_id", "persons", ["external_id"])
    op.create_index("ix_persons_email", "persons", ["email"])
    op.create_index("ix_persons_slack_user_id", "persons", ["slack_user_id"])
    op.create_index("ix_persons_github_login", "persons", ["github_login"])
    op.create_index("ix_persons_team_id", "persons", ["team_id"])

    # ── Services ─────────────────────────────────────────────────────────────
    op.create_table(
        "services",
        *_node_columns(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("repo_url", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="active"),
    )
    op.create_index("ix_services_external_id", "services", ["external_id"])

    # ── Repositories ─────────────────────────────────────────────────────────
    op.create_table(
        "repositories",
        *_node_columns(),
        sa.Column("full_name", sa.String(512), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.String(128), nullable=False, server_default="main"),
        sa.Column("language", sa.String(64), nullable=True),
        sa.Column("owner_team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_repositories_external_id", "repositories", ["external_id"])

    # ── Decisions ────────────────────────────────────────────────────────────
    op.create_table(
        "decisions",
        *_node_columns(),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="open"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
    )
    op.create_index("ix_decisions_external_id", "decisions", ["external_id"])

    # ── Tasks ────────────────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        *_node_columns(),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("assignee_id", UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("jira_key", sa.String(64), nullable=True),
    )
    op.create_index("ix_tasks_external_id", "tasks", ["external_id"])
    op.create_index("ix_tasks_jira_key", "tasks", ["jira_key"])

    # ── Documents ────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        *_node_columns(),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("doc_url", sa.String(1024), nullable=True),
        sa.Column("doc_type", sa.String(64), nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_documents_external_id", "documents", ["external_id"])

    # ── Edges ────────────────────────────────────────────────────────────────
    op.create_table(
        "edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("inferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("properties", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=True),
    )
    op.create_index("ix_edges_edge_type", "edges", ["edge_type"])
    op.create_index("ix_edges_source", "edges", ["source_id", "source_type"])
    op.create_index("ix_edges_target", "edges", ["target_id", "target_type"])
    op.create_index("ix_edges_type_source", "edges", ["edge_type", "source_id"])

    # ── Node embeddings ──────────────────────────────────────────────────────
    op.create_table(
        "node_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", UUID(as_uuid=True), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_node_embeddings_node_id", "node_embeddings", ["node_id"])
    op.create_index(
        "ix_node_embeddings_node_id_type", "node_embeddings", ["node_id", "node_type"], unique=True
    )

    # ── Chunk embeddings ─────────────────────────────────────────────────────
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", UUID(as_uuid=True), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chunk_embeddings_node_id", "chunk_embeddings", ["node_id"])
    op.create_index("ix_chunk_embeddings_node", "chunk_embeddings", ["node_id", "node_type"])


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_table("node_embeddings")
    op.drop_table("edges")
    op.drop_table("documents")
    op.drop_table("tasks")
    op.drop_table("decisions")
    op.drop_table("repositories")
    op.drop_table("services")
    op.drop_table("persons")
    op.drop_table("teams")
