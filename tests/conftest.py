# Secrets must be in the environment before anything imports miya_server.config,
# because get_settings() is lru_cached and db/base.py calls it at import time.
# Env vars outrank the .env file in pydantic-settings, so this wins locally too.
import os

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-bytes-long")
os.environ.setdefault("MEDIA_URL_SECRET", "test-media-secret-at-least-32-bytes")
os.environ.setdefault("GOOGLE_IOS_CLIENT_ID", "test-client-id.apps.googleusercontent.com")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from miya_server.auth import tokens
from miya_server.main import app

pytest_plugins = ["db_conftest"]


@pytest.fixture
async def client():
    """Unauthenticated. For /health, /media, and for asserting that gated
    fields actually refuse anonymous callers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authed_client(auth_user):
    """Carries a real access token for a real user row -- the permission class
    resolves the viewer against the database, so a synthetic token would be
    rejected. Every test that reads the library needs this."""
    access_token, _ = tokens.mint_access_token(auth_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as ac:
        yield ac


def signed(path: str) -> str:
    """A /media path carrying the query signature the router now requires.

    Reuses the production signer rather than reimplementing it, so a change to
    the scheme cannot leave these tests passing against stale expectations."""
    from urllib.parse import urlparse

    from miya_server.media.storage import _signed

    parsed = urlparse(_signed(path))
    return f"{parsed.path}?{parsed.query}"
