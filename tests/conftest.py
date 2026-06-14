"""
Shared pytest fixtures.

`db_session` and `client` exercise the real Postgres connection configured via
`settings.database_url`. If the database is unreachable (e.g. `docker compose up
-d postgres` hasn't been run), tests using `db_session` are skipped; `client`
only needs the app to import, not the database to be live.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session bound to a connection-level transaction, rolled back after the test."""
    connection = engine.connect()
    try:
        await connection.start()
    except Exception as exc:
        pytest.skip(f"database unavailable: {exc}")
        return

    await connection.begin()
    session = AsyncSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        await session.close()
        await connection.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
