"""
Concrete repositories for each graph node type.

Extends BaseRepository with typed per-model methods. Used by agents and
routes that need to look up, filter, or upsert specific node types without
dropping to raw SQLAlchemy in application code.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.nodes import Decision, Document, Person, Repository, Service, Task, Team
from app.db.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def get_by_name(self, name: str) -> Team | None:
        result = await self.session.execute(select(Team).where(Team.name == name))
        return result.scalar_one_or_none()

    async def list_with_members(self, limit: int = 100) -> list[Team]:
        result = await self.session.execute(select(Team).limit(limit))
        return list(result.scalars().all())


class PersonRepository(BaseRepository[Person]):
    model = Person

    async def get_by_slack_id(self, slack_user_id: str) -> Person | None:
        result = await self.session.execute(
            select(Person).where(Person.slack_user_id == slack_user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_github_login(self, login: str) -> Person | None:
        result = await self.session.execute(
            select(Person).where(Person.github_login == login)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Person | None:
        result = await self.session.execute(
            select(Person).where(Person.email == email)
        )
        return result.scalar_one_or_none()

    async def list_by_team(self, team_id: uuid.UUID) -> list[Person]:
        result = await self.session.execute(
            select(Person).where(Person.team_id == team_id)
        )
        return list(result.scalars().all())


class ServiceRepository(BaseRepository[Service]):
    model = Service

    async def get_by_name(self, name: str) -> Service | None:
        result = await self.session.execute(select(Service).where(Service.name == name))
        return result.scalar_one_or_none()

    async def list_unowned(self) -> list[Service]:
        result = await self.session.execute(
            select(Service).where(Service.owner_team_id.is_(None))
        )
        return list(result.scalars().all())

    async def list_by_team(self, team_id: uuid.UUID) -> list[Service]:
        result = await self.session.execute(
            select(Service).where(Service.owner_team_id == team_id)
        )
        return list(result.scalars().all())


class RepositoryRepo(BaseRepository[Repository]):
    """Named RepositoryRepo to avoid shadowing the built-in `Repository` model."""
    model = Repository

    async def get_by_full_name(self, full_name: str) -> Repository | None:
        result = await self.session.execute(
            select(Repository).where(Repository.full_name == full_name)
        )
        return result.scalar_one_or_none()

    async def list_by_team(self, team_id: uuid.UUID) -> list[Repository]:
        result = await self.session.execute(
            select(Repository).where(Repository.owner_team_id == team_id)
        )
        return list(result.scalars().all())


class DecisionRepository(BaseRepository[Decision]):
    model = Decision

    async def list_open(self, limit: int = 50) -> list[Decision]:
        result = await self.session.execute(
            select(Decision).where(Decision.status == "open").limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_decider(self, person_id: uuid.UUID) -> list[Decision]:
        result = await self.session.execute(
            select(Decision).where(Decision.decided_by_id == person_id)
        )
        return list(result.scalars().all())


class TaskRepository(BaseRepository[Task]):
    model = Task

    async def list_open_by_team(self, team_id: uuid.UUID, limit: int = 50) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .where(Task.team_id == team_id, Task.status.in_(["open", "in_progress"]))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_overdue(self, before: Any) -> list[Task]:
        result = await self.session.execute(
            select(Task).where(
                Task.status.in_(["open", "in_progress"]),
                Task.due_date < before,
            )
        )
        return list(result.scalars().all())

    async def get_by_jira_key(self, jira_key: str) -> Task | None:
        result = await self.session.execute(
            select(Task).where(Task.jira_key == jira_key)
        )
        return result.scalar_one_or_none()


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.owner_id == owner_id)
        )
        return list(result.scalars().all())
