"""
Async SQLAlchemy engine, session factory, and dependency injection helpers.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.db_echo,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager – commits on success, rolls back on exception."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency wrapper around db_session."""
    async with db_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables (dev / test only; production uses Alembic migrations)."""
    from app.db import models  # noqa: F401 – import all models so they register with Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database.tables_created")


async def close_db() -> None:
    await engine.dispose()
    logger.info("database.connection_closed")