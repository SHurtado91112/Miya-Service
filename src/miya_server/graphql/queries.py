import strawberry
from strawberry import relay

from miya_server.graphql.pagination import (
    build_connection,
    clamp_first,
    decode_cursor,
    reject_backward,
)
from miya_server.graphql.types.album import Album, AlbumConnection, build_album
from miya_server.graphql.types.media_item import MediaItem, build_media_entries
from miya_server.graphql.types.section import Section, build_section_entries
from miya_server.repositories import albums as albums_repo
from miya_server.repositories import media_items as media_items_repo
from miya_server.repositories import sections as sections_repo

_ALBUM_CURSOR_PREFIX = "album"


async def _build_section(session, db_section) -> Section:
    entries = await sections_repo.list_section_entries(session, db_section.id)
    items = await build_section_entries(session, entries)
    return Section(
        id=strawberry.ID(str(db_section.id)),
        slug=db_section.slug,
        title=db_section.title,
        items=items,
    )


@strawberry.type
class Query:
    node: relay.Node = relay.node()

    @strawberry.field
    async def sections(self, info: strawberry.Info) -> list[Section]:
        session = info.context.session
        db_sections = await sections_repo.list_sections(session)
        return [await _build_section(session, db_section) for db_section in db_sections]

    @strawberry.field
    async def section(self, info: strawberry.Info, slug: str) -> Section | None:
        session = info.context.session
        db_section = await sections_repo.get_section_by_slug(session, slug)
        if db_section is None:
            return None
        return await _build_section(session, db_section)

    @strawberry.field
    async def albums(
        self,
        info: strawberry.Info,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> AlbumConnection:
        reject_backward(last, before)
        limit = clamp_first(first)
        after_key = (
            decode_cursor(_ALBUM_CURSOR_PREFIX, after) if after is not None else None
        )
        session = info.context.session

        rows = await albums_repo.list_albums_page(
            session,
            limit=limit + 1,
            after_title=after_key[0] if after_key else None,
            after_id=after_key[1] if after_key else None,
        )
        has_next_page = len(rows) > limit
        page = rows[:limit]

        return build_connection(
            AlbumConnection,
            page,
            prefix=_ALBUM_CURSOR_PREFIX,
            after=after,
            has_next_page=has_next_page,
            key=lambda row: (row.title, row.id),
            node=build_album,
        )

    @strawberry.field
    async def album(self, info: strawberry.Info, slug: str) -> Album | None:
        session = info.context.session
        db_album = await albums_repo.get_album_by_slug(session, slug)
        return build_album(db_album) if db_album else None

    @strawberry.field
    async def search_media(self, info: strawberry.Info, query: str) -> list[MediaItem]:
        session = info.context.session
        db_items = await media_items_repo.search_media_items(session, query)
        return await build_media_entries(session, db_items)
