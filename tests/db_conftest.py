"""Fixtures for tests that need a live Postgres. Not autouse -- only the
DB-backed test modules (test_graphql_sections.py, test_graphql_albums.py)
opt in via `pytestmark = pytest.mark.usefixtures("seeded_db")`, so
schema-only/health tests never attempt a DB connection.

Skips automatically if the configured Postgres isn't reachable -- run
`docker compose up -d && alembic upgrade head` first for these to execute."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.base import async_session_factory, engine
from miya_server.seed.seed_data import run as run_seed


async def _db_available() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 -- connectivity probe, any failure means "unavailable"
        return False


@pytest_asyncio.fixture(scope="session")
async def seeded_db():
    if not await _db_available():
        pytest.skip("Postgres not reachable at DATABASE_URL -- skipping DB-backed tests")
    await run_seed()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
