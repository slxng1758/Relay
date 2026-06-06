"""
ORM models for graph nodes: Team, Person, Service, Repository, Decision, Task.
Each node type maps to its own table; edges live in graph/edges/models.py.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class NodeType(StrEnum):
    TEAM = "team"
    PERSON = "person"
    SERVICE = "service"
    REPOSITORY = "repository"
    DECISION = "decision"
    TASK = "task"
    DOCUMENT = "document"
    INCIDENT = "incident"


class SourceSystem(StrEnum):
    SLACK = "slack"
    GITHUB = "github"
    JIRA = "jira"
    GDOCS = "gdocs"
    MANUAL = "manual"


# ── Base mixin ────────────────────────────────────────────────────────────────

class NodeMixin:
    """Common columns shared by all graph node tables."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(String(512), index=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )


# ── Node tables ───────────────────────────────────────────────────────────────

class Team(NodeMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slack_channel_id: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)

    members: Mapped[list["Person"]] = relationship(
        "Person", back_populates="team", lazy="selectin"
    )

    __table_args__ = (Index("ix_teams_name", "name"),)


class Person(NodeMixin, Base):
    __tablename__ = "persons"

    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    github_login: Mapped[str | None] = mapped_column(String(128), index=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(128))
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    team: Mapped["Team | None"] = relationship("Team", back_populates="members")


class Service(NodeMixin, Base):
    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    repo_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(64), default="active")


class Repository(NodeMixin, Base):
    __tablename__ = "repositories"

    full_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    language: Mapped[str | None] = mapped_column(String(64))
    owner_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )


class Decision(NodeMixin, Base):
    __tablename__ = "decisions"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="open")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL")
    )
    source_url: Mapped[str | None] = mapped_column(String(1024))


class Task(NodeMixin, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="open")
    priority: Mapped[str | None] = mapped_column(String(32))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    jira_key: Mapped[str | None] = mapped_column(String(64), index=True)


class Document(NodeMixin, Base):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    doc_url: Mapped[str | None] = mapped_column(String(1024))
    doc_type: Mapped[str | None] = mapped_column(String(64))  # rfc | runbook | spec | adr
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL")
    )