import strawberry
from strawberry import relay

from miya_server.graphql.types.author import Author
from miya_server.graphql.types.section import SectionEntry
from miya_server.repositories import media_items as media_items_repo


@strawberry.type
class SearchEntryEdge:
    cursor: str
    node: SectionEntry


@strawberry.type
class SearchEntryConnection:
    """Forward Relay connection of matching songs / photos / albums, ordered by
    (title, id). Explicitly hand-rolled (rather than `relay.Connection[...]`)
    so the union node yields a cleanly named `SearchEntryEdge`. `_query` /
    `_section_slug` are carried so `totalCount` can recount the same filter."""

    page_info: relay.PageInfo
    edges: list[SearchEntryEdge]

    _query: strawberry.Private[str]
    _section_slug: strawberry.Private[str | None]

    @strawberry.field
    async def total_count(self, info: strawberry.Info) -> int:
        return await media_items_repo.count_search_section_entries(
            info.context.session, self._query, section_slug=self._section_slug
        )


@strawberry.type
class SearchResult:
    """`search` payload: a paginated connection of matching media entries plus
    the (small, unpaginated) set of authors whose name matched."""

    entries: SearchEntryConnection
    authors: list[Author]
