import strawberry
from strawberry import relay

from miya_server.graphql.pagination import (
    build_connection,
    clamp_first,
    decode_cursor,
    encode_cursor,
    reject_backward,
)
from miya_server.graphql.types.album import Album, AlbumConnection, build_album
from miya_server.graphql.types.author import build_author
from miya_server.graphql.types.media_item import build_media_entry_map
from miya_server.graphql.types.search import (
    SearchEntryConnection,
    SearchEntryEdge,
    SearchResult,
)
from miya_server.graphql.types.section import Section, build_section_entries
from miya_server.repositories import albums as albums_repo
from miya_server.repositories import authors as authors_repo
from miya_server.repositories import media_items as media_items_repo
from miya_server.repositories import sections as sections_repo
from miya_server.repositories.media_items import SearchEntryRow

_ALBUM_CURSOR_PREFIX = "album"
_SEARCH_CURSOR_PREFIX = "search"


async def _build_section(session, db_section) -> Section:
    entries = await sections_repo.list_section_entries(session, db_section.id)
    items = await build_section_entries(session, entries)
    return Section(
        id=strawberry.ID(str(db_section.id)),
        slug=db_section.slug,
        title=db_section.title,
        items=items,
    )


async def _hydrate_search_rows(
    session, rows: list[SearchEntryRow]
) -> dict[tuple[str, object], object]:
    """Batch-hydrate a page of `SearchEntryRow` pointers into built
    Song/Photo/Album objects, keyed by `(row_kind, id)` for order-preserving
    lookup by the connection builder."""
    media_ids = [row.id for row in rows if row.row_kind == "media_item"]
    album_ids = [row.id for row in rows if row.row_kind == "album"]

    node_map: dict[tuple[str, object], object] = {}

    if media_ids:
        db_items = await media_items_repo.batch_get_media_items(session, media_ids)
        entry_map = await build_media_entry_map(
            session, [item for item in db_items if item is not None]
        )
        for item_id, node in entry_map.items():
            node_map[("media_item", item_id)] = node

    if album_ids:
        db_albums = await albums_repo.batch_get_albums(session, album_ids)
        for db_album in db_albums:
            if db_album is not None:
                node_map[("album", db_album.id)] = build_album(db_album)

    return node_map


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
    async def search(
        self,
        info: strawberry.Info,
        query: str,
        section_slug: str | None = None,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> SearchResult:
        """Fuzzy/typo-tolerant search (pg_trgm) over media title / subtitle /
        song artist / parent-album title, plus authors matched by name.
        `sectionSlug` scopes both to one section's membership. `entries` is a
        forward Relay connection ordered by relevance (trigram score, then id);
        `authors` is a small unpaginated list ranked by name similarity."""
        reject_backward(last, before)
        limit = clamp_first(first)
        after_key = (
            decode_cursor(_SEARCH_CURSOR_PREFIX, after) if after is not None else None
        )
        session = info.context.session

        rows = await media_items_repo.search_section_entries_page(
            session,
            query,
            section_slug=section_slug,
            limit=limit + 1,
            after_score=float(after_key[0]) if after_key else None,
            after_id=after_key[1] if after_key else None,
        )
        has_next_page = len(rows) > limit
        page = rows[:limit]

        node_map = await _hydrate_search_rows(session, page)
        page = [row for row in page if (row.row_kind, row.id) in node_map]

        edges = [
            SearchEntryEdge(
                cursor=encode_cursor(_SEARCH_CURSOR_PREFIX, repr(row.score), row.id),
                node=node_map[(row.row_kind, row.id)],
            )
            for row in page
        ]
        entries = SearchEntryConnection(
            page_info=relay.PageInfo(
                has_next_page=has_next_page,
                has_previous_page=after is not None,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            edges=edges,
            _query=query,
            _section_slug=section_slug,
        )

        db_authors = await authors_repo.search_authors(
            session, query, section_slug=section_slug
        )
        return SearchResult(
            entries=entries,
            authors=[build_author(db_author) for db_author in db_authors],
        )
