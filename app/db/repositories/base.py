"""
Generic async repository pattern.
Concrete repositories inherit and add domain-specific queries.
"""
import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.logging import get_logger

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, external_id: str, source_system: str
    ) -> ModelT | None:
        result = await self.session.execute(
            select(self.model).where(  # type: ignore[attr-defined]
                self.model.external_id == external_id,  # type: ignore[attr-defined]
                self.model.source_system == source_system,  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one_or_none()

    async def list(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)  # type: ignore[attr-defined]
        )
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> ModelT:
        instance = self.model(**kwargs)  # type: ignore[call-arg]
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id: uuid.UUID, **kwargs: Any) -> ModelT | None:
        await self.session.execute(
            update(self.model)  # type: ignore[arg-type]
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(**kwargs)
        )
        return await self.get(id)

    async def upsert_by_external_id(
        self, external_id: str, source_system: str, **kwargs: Any
    ) -> tuple[ModelT, bool]:
        """Return (instance, created). Created=True means a new row was inserted."""
        existing = await self.get_by_external_id(external_id, source_system)
        if existing:
            updated = await self.update(existing.id, **kwargs)  # type: ignore[attr-defined]
            return updated, False  # type: ignore[return-value]
        new = await self.create(
            external_id=external_id, source_system=source_system, **kwargs
        )
        return new, True

    async def delete(self, id: uuid.UUID) -> bool:
        instance = await self.get(id)
        if instance:
            await self.session.delete(instance)
            return True
        return False