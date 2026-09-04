import pytest
from httpx import ASGITransport, AsyncClient

from miya_server.main import app

pytest_plugins = ["db_conftest"]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
