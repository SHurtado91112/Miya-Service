from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Album, MediaItem, Section
from miya_server.db.models.associations import section_albums, section_items


@dataclass
class SectionEntryRow:
    """A single ordered slot in a section's item list -- either a media item
    or a full album card, mirroring the client's mixed section content."""

    kind: Literal["media_item", "album"]
    sort_order: int
    media_item: MediaItem | None = None
    album: Album | None = None


async def list_sections(session: AsyncSession) -> list[Section]:
    result = await session.execute(select(Section).order_by(Section.sort_order))
    return list(result.scalars().all())


async def get_section_by_slug(session: AsyncSession, slug: str) -> Section | None:
    result = await session.execute(select(Section).where(Section.slug == slug))
    return result.scalar_one_or_none()


async def list_section_entries(session: AsyncSession, section_id: UUID) -> list[SectionEntryRow]:
    """One query for member media items, one for member albums; merged and
    sorted in Python by their respective sort_order -- avoids N+1 per section."""
    item_stmt = (
        select(MediaItem, section_items.c.sort_order)
        .join(section_items, MediaItem.id == section_items.c.media_item_id)
        .where(section_items.c.section_id == section_id)
    )
    album_stmt = (
        select(Album, section_albums.c.sort_order)
        .join(section_albums, Album.id == section_albums.c.album_id)
        .where(section_albums.c.section_id == section_id)
    )
    item_rows = (await session.execute(item_stmt)).all()
    album_rows = (await session.execute(album_stmt)).all()

    entries = [
        SectionEntryRow(kind="media_item", sort_order=sort_order, media_item=item)
        for item, sort_order in item_rows
    ] + [
        SectionEntryRow(kind="album", sort_order=sort_order, album=album)
        for album, sort_order in album_rows
    ]

    # Fold album members away: a media item whose album is also an album card in
    # this section is dropped -- the card stands in for it.
    album_ids_in_section = {
        entry.album.id for entry in entries if entry.kind == "album" and entry.album is not None
    }
    entries = [
        entry
        for entry in entries
        if not (
            entry.kind == "media_item"
            and entry.media_item is not None
            and entry.media_item.album_id in album_ids_in_section
        )
    ]

    entries.sort(key=lambda entry: entry.sort_order)
    return entries
