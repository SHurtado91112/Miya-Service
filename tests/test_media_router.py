import io
import uuid
from pathlib import Path

import pytest
from conftest import signed
from PIL import Image
from sqlalchemy import select

from miya_server.config import Settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import Author, MediaFile, MediaItem, Photo
from miya_server.media import ingest

pytestmark = pytest.mark.usefixtures("seeded_db")


def _settings_with_media_root(media_root: Path) -> Settings:
    return Settings(media_root=media_root)


def _real_jpeg(path: Path, size=(1200, 800)) -> Path:
    Image.new("RGB", size, color=(90, 140, 200)).save(path, format="JPEG")
    return path


def _override_settings(monkeypatch, media_root: Path) -> None:
    settings_override = _settings_with_media_root(media_root)
    monkeypatch.setattr(ingest, "get_settings", lambda: settings_override)
    monkeypatch.setattr("miya_server.media.router.get_settings", lambda: settings_override)


async def test_unknown_media_file_returns_404(client):
    response = await client.get(signed(f"/media/{uuid.uuid4()}"))
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
        response = await client.get(signed(f"/media/{file_id}"))
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


async def _reset_media_item(slug: str, file_ids: list[uuid.UUID]) -> None:
    async with async_session_factory() as session:
        item = (
            await session.execute(select(MediaItem).where(MediaItem.slug == slug))
        ).scalar_one()
        item.primary_media_file_id = None
        photo = (
            await session.execute(select(Photo).where(Photo.media_item_id == item.id))
        ).scalar_one_or_none()
        if photo is not None:
            photo.image_file_id = None
        await session.flush()
        for fid in file_ids:
            mf = await session.get(MediaFile, fid)
            if mf is not None:
                await session.delete(mf)
        await session.commit()


async def test_ingest_generates_thumbnail_and_serves_it(client, tmp_path, monkeypatch):
    # "sunrise-ridge" is a seeded photo slug (seed/fixtures/home_sections.json).
    _real_jpeg(tmp_path / "sunrise-ridge.jpg", size=(1500, 1000))
    media_root = tmp_path / "media_root"
    _override_settings(monkeypatch, media_root)

    await ingest.run(tmp_path)

    async with async_session_factory() as session:
        item = (
            await session.execute(select(MediaItem).where(MediaItem.slug == "sunrise-ridge"))
        ).scalar_one()
        file_id = item.primary_media_file_id
        media_file = await session.get(MediaFile, file_id)
        assert media_file.thumbnail_relative_path is not None
        assert media_file.thumbnail_relative_path.endswith("_thumb.webp")
        assert media_file.thumbnail_mime_type == "image/webp"
        assert max(media_file.thumbnail_width, media_file.thumbnail_height) == 512

    try:
        full = await client.get(signed(f"/media/{file_id}"))
        assert full.status_code == 200
        assert full.headers["content-type"] == "image/jpeg"

        thumb = await client.get(signed(f"/media/{file_id}/thumb"))
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/webp"
        assert thumb.headers["cache-control"] == "public, max-age=31536000, immutable"
        img = Image.open(io.BytesIO(thumb.content))
        assert img.format == "WEBP"
        assert max(img.size) == 512
        assert img.size == (512, 341)  # 3:2 aspect preserved
    finally:
        await _reset_media_item("sunrise-ridge", [file_id])


async def test_thumb_endpoint_falls_back_to_original_when_no_thumbnail(
    client, tmp_path, monkeypatch
):
    # Fake JPEG bytes -> thumbnail generation fails (caught), columns stay NULL.
    (tmp_path / "harbor-fog.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")
    _override_settings(monkeypatch, tmp_path / "media_root")

    await ingest.run(tmp_path)

    async with async_session_factory() as session:
        item = (
            await session.execute(select(MediaItem).where(MediaItem.slug == "harbor-fog"))
        ).scalar_one()
        file_id = item.primary_media_file_id
        media_file = await session.get(MediaFile, file_id)
        assert media_file.thumbnail_relative_path is None

    try:
        thumb = await client.get(signed(f"/media/{file_id}/thumb"))
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/jpeg"  # served the original
    finally:
        await _reset_media_item("harbor-fog", [file_id])


async def test_ingest_author_portrait_by_prefixed_slug(client, tmp_path, monkeypatch):
    # "radiohead" is a seeded author (song artist -> backfilled author).
    _real_jpeg(tmp_path / "author-radiohead.jpg", size=(900, 1200))
    _override_settings(monkeypatch, tmp_path / "media_root")

    await ingest.run(tmp_path)

    async with async_session_factory() as session:
        author = (
            await session.execute(select(Author).where(Author.slug == "radiohead"))
        ).scalar_one()
        file_id = author.profile_media_file_id
        assert file_id is not None
        media_file = await session.get(MediaFile, file_id)
        assert media_file.relative_path.startswith("authors/")
        assert media_file.thumbnail_relative_path is not None

    try:
        assert (await client.get(signed(f"/media/{file_id}"))).status_code == 200
        thumb = await client.get(signed(f"/media/{file_id}/thumb"))
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/webp"
        assert max(Image.open(io.BytesIO(thumb.content)).size) == 512
    finally:
        async with async_session_factory() as session:
            author = (
                await session.execute(select(Author).where(Author.slug == "radiohead"))
            ).scalar_one()
            author.profile_media_file_id = None
            await session.flush()
            mf = await session.get(MediaFile, file_id)
            if mf is not None:
                await session.delete(mf)
            await session.commit()


async def test_ingest_author_prefix_with_no_matching_author_is_skipped(
    tmp_path, monkeypatch
):
    _real_jpeg(tmp_path / "author-nobody-here.jpg")
    _override_settings(monkeypatch, tmp_path / "media_root")

    async def _authors_rows() -> int:
        async with async_session_factory() as session:
            return len(
                (
                    await session.execute(
                        select(MediaFile).where(MediaFile.relative_path.like("authors/%"))
                    )
                ).scalars().all()
            )

    before = await _authors_rows()
    await ingest.run(tmp_path)
    assert await _authors_rows() == before  # no row created for an unknown author


async def test_ingest_author_portrait_is_idempotent(tmp_path, monkeypatch):
    _real_jpeg(tmp_path / "author-radiohead.jpg", size=(900, 1200))
    _override_settings(monkeypatch, tmp_path / "media_root")

    await ingest.run(tmp_path)
    async with async_session_factory() as session:
        author = (
            await session.execute(select(Author).where(Author.slug == "radiohead"))
        ).scalar_one()
        first_id = author.profile_media_file_id
        count_before = len(
            (
                await session.execute(
                    select(MediaFile).where(MediaFile.relative_path.like("authors/%"))
                )
            ).scalars().all()
        )

    await ingest.run(tmp_path)
    try:
        async with async_session_factory() as session:
            author = (
                await session.execute(select(Author).where(Author.slug == "radiohead"))
            ).scalar_one()
            assert author.profile_media_file_id == first_id
            count_after = len(
                (
                    await session.execute(
                        select(MediaFile).where(MediaFile.relative_path.like("authors/%"))
                    )
                ).scalars().all()
            )
        assert count_after == count_before
    finally:
        async with async_session_factory() as session:
            author = (
                await session.execute(select(Author).where(Author.slug == "radiohead"))
            ).scalar_one()
            author.profile_media_file_id = None
            await session.flush()
            mf = await session.get(MediaFile, first_id)
            if mf is not None:
                await session.delete(mf)
            await session.commit()
