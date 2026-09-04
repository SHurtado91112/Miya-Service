from typing import Annotated

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.graphql.types.album import Album, build_album
from miya_server.graphql.types.media_item import Photo, Song, build_media_entry_map
from miya_server.repositories.sections import SectionEntryRow

SectionEntry = Annotated[Song | Photo | Album, strawberry.union("SectionEntry")]


@strawberry.type
class Section:
    id: strawberry.ID
    slug: str
    title: str
    items: list[SectionEntry]


async def build_section_entries(session: AsyncSession, entries: list[SectionEntryRow]) -> list:
    media_items = [entry.media_item for entry in entries if entry.kind == "media_item" and entry.media_item]
    entry_map = await build_media_entry_map(session, media_items)

    result = []
    for entry in entries:
        if entry.kind == "media_item" and entry.media_item is not None:
            built = entry_map.get(entry.media_item.id)
            if built is not None:
                result.append(built)
        elif entry.kind == "album" and entry.album is not None:
            result.append(build_album(entry.album))
    return result
