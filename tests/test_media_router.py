import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from miya_server.config import Settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import MediaFile, MediaItem
from miya_server.media import ingest

pytestmark = pytest.mark.usefixtures("seeded_db")


def _settings_with_media_root(media_root: Path) -> Settings:
    return Settings(media_root=media_root)


async def test_unknown_media_file_returns_404(client):
    response = await client.get(f"/media/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_ingest_then_serve_image(client, tmp_path, monkeypatch):
    # "midnight-city" is a seeded song slug (see seed/fixtures/home_sections.json).
    source = tmp_path / "midnight-city.jpg"
    source.write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg-but-good-enough-for-mime-sniffing")

    media_root = tmp_path / "media_root"
    settings_override = _settings_with_media_root(media_root)
    monkeypatch.setattr(ingest, "get_settings", lambda: settings_override)
    monkeypatch.setattr("miya_server.media.router.get_settings", lambda: settings_override)

    await ingest.run(tmp_path)

    async with async_session_factory() as session:
        item = (
            await session.execute(select(MediaItem).where(MediaItem.slug == "midnight-city"))
        ).scalar_one()
        file_id = item.primary_media_file_id
        assert file_id is not None

    try:
        response = await client.get(f"/media/{file_id}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")
    finally:
        # Ingest tests write real FKs onto seeded rows and create a media_files
        # row pointing at tmp_path (cleaned up by pytest after this test) --
        # reset both so the dev DB (session-scoped seed, not a per-test
        # transaction) isn't left dirty or pointing at a deleted file.
        async with async_session_factory() as session:
            item = (
                await session.execute(select(MediaItem).where(MediaItem.slug == "midnight-city"))
            ).scalar_one()
            item.primary_media_file_id = None
            await session.flush()
            media_file = await session.get(MediaFile, file_id)
            if media_file is not None:
                await session.delete(media_file)
            await session.commit()
