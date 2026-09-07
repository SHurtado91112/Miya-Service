"""`backfill-thumbnails` CLI: generates thumbnails for pre-existing media_files
rows that have none, and is a no-op on a second run.
"""

import uuid

import pytest
from PIL import Image

from miya_server.config import Settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import MediaFile
from miya_server.media import thumbnails

pytestmark = pytest.mark.usefixtures("seeded_db")


async def test_backfill_fills_missing_thumbnails_then_no_ops(tmp_path, monkeypatch):
    media_root = tmp_path / "media_root"
    (media_root / "photos").mkdir(parents=True)
    settings_override = Settings(media_root=media_root)
    monkeypatch.setattr(thumbnails, "get_settings", lambda: settings_override)

    rel = f"photos/{uuid.uuid4()}.png"
    Image.new("RGB", (1400, 700), color=(10, 20, 30)).save(media_root / rel, format="PNG")

    file_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            MediaFile(
                id=file_id,
                relative_path=rel,
                mime_type="image/png",
                size_bytes=(media_root / rel).stat().st_size,
                width=1400,
                height=700,
            )
        )
        await session.commit()

    try:
        await thumbnails.run()

        async with async_session_factory() as session:
            mf = await session.get(MediaFile, file_id)
            assert mf.thumbnail_relative_path == rel.replace(".png", "_thumb.webp")
            assert mf.thumbnail_mime_type == "image/webp"
            assert (mf.thumbnail_width, mf.thumbnail_height) == (512, 256)
        assert (media_root / mf.thumbnail_relative_path).is_file()
        first_mtime = (media_root / mf.thumbnail_relative_path).stat().st_mtime_ns

        # Second run must skip the now-populated row (file untouched).
        await thumbnails.run()
        assert (media_root / mf.thumbnail_relative_path).stat().st_mtime_ns == first_mtime
    finally:
        async with async_session_factory() as session:
            mf = await session.get(MediaFile, file_id)
            if mf is not None:
                await session.delete(mf)
            await session.commit()
