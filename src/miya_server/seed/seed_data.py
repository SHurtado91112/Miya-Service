"""Loads the bundled JSON fixtures (copied from the Miya iOS app's mock data)
into Postgres. Idempotent: upserts by unique slug, safe to re-run.

Picsum `imageURL`s are intentionally dropped -- media_files/FKs are populated
later by the (Phase 3) ingest script once real self-hosted files exist.

Run via: uv run seed
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.base import async_session_factory
from miya_server.db.models import Album, MediaItem, Photo, Section, Song
from miya_server.db.models.associations import section_albums, section_items

FIXTURES_DIR = Path(__file__).parent / "fixtures"


async def _get_or_create_album(session: AsyncSession, data: dict[str, Any]) -> Album:
    slug = data["id"]
    album = (await session.execute(select(Album).where(Album.slug == slug))).scalar_one_or_none()
    if album is None:
        album = Album(slug=slug)
        session.add(album)
    album.title = data["title"]
    album.subtitle = data.get("subtitle", "")
    album.system_image = data.get("systemImage", "")
    await session.flush()
    return album


async def _upsert_media_item(
    session: AsyncSession, data: dict[str, Any], *, album_id: Any | None
) -> MediaItem:
    slug = data["id"]
    kind = data["kind"]
    item = (
        await session.execute(select(MediaItem).where(MediaItem.slug == slug))
    ).scalar_one_or_none()
    if item is None:
        item = MediaItem(slug=slug, kind=kind)
        session.add(item)

    item.title = data["title"]
    item.subtitle = data.get("subtitle", "")
    item.system_image = data.get("systemImage", "")
    item.detail = data.get("detail", "")
    if album_id is not None:
        item.album_id = album_id
    await session.flush()

    if kind == "song":
        song = (
            await session.execute(select(Song).where(Song.media_item_id == item.id))
        ).scalar_one_or_none()
        if song is None:
            song = Song(media_item_id=item.id, artist=data.get("subtitle", ""))
            session.add(song)
        else:
            song.artist = data.get("subtitle", "")
    elif kind == "photo":
        photo = (
            await session.execute(select(Photo).where(Photo.media_item_id == item.id))
        ).scalar_one_or_none()
        if photo is None:
            photo = Photo(media_item_id=item.id)
            session.add(photo)

    return item


async def _seed_albums(session: AsyncSession) -> dict[str, Album]:
    albums_data = json.loads((FIXTURES_DIR / "albums.json").read_text())
    slug_to_album: dict[str, Album] = {}
    for album_data in albums_data:
        album = await _get_or_create_album(session, album_data)
        slug_to_album[album.slug] = album
        for item_data in album_data.get("items", []):
            await _upsert_media_item(session, item_data, album_id=album.id)
    return slug_to_album


async def _seed_sections(session: AsyncSession, slug_to_album: dict[str, Album]) -> None:
    sections_data = json.loads((FIXTURES_DIR / "home_sections.json").read_text())
    for sort_order, section_data in enumerate(sections_data):
        slug = section_data["id"]
        section = (
            await session.execute(select(Section).where(Section.slug == slug))
        ).scalar_one_or_none()
        if section is None:
            section = Section(slug=slug, sort_order=sort_order)
            session.add(section)
        section.title = section_data["title"]
        section.sort_order = sort_order
        await session.flush()

        item_order = 0
        album_order = 0
        for item_data in section_data.get("items", []):
            if item_data["kind"] == "album":
                album = slug_to_album.get(item_data["id"])
                if album is None:
                    # Album referenced in a section but not defined in albums.json --
                    # create a minimal placeholder so the section link is still valid.
                    album = await _get_or_create_album(session, item_data)
                    slug_to_album[album.slug] = album
                await session.execute(
                    section_albums.delete().where(
                        (section_albums.c.section_id == section.id)
                        & (section_albums.c.album_id == album.id)
                    )
                )
                await session.execute(
                    section_albums.insert().values(
                        section_id=section.id, album_id=album.id, sort_order=album_order
                    )
                )
                album_order += 1
                continue

            album_id = None
            if item_data.get("albumID"):
                referenced_album = slug_to_album.get(item_data["albumID"])
                album_id = referenced_album.id if referenced_album else None

            item = await _upsert_media_item(session, item_data, album_id=album_id)
            await session.execute(
                section_items.delete().where(
                    (section_items.c.section_id == section.id)
                    & (section_items.c.media_item_id == item.id)
                )
            )
            await session.execute(
                section_items.insert().values(
                    section_id=section.id, media_item_id=item.id, sort_order=item_order
                )
            )
            item_order += 1


async def run() -> None:
    async with async_session_factory() as session:
        slug_to_album = await _seed_albums(session)
        await _seed_sections(session, slug_to_album)
        await session.commit()
    print("Seed complete.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
