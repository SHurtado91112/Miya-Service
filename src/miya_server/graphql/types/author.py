import uuid

import strawberry
from strawberry import relay

from miya_server.db.models import Author as DBAuthor
from miya_server.graphql.pagination import (
    build_connection,
    clamp_first,
    decode_cursor,
    reject_backward,
)
from miya_server.graphql.types.media_item import MediaItem, build_media_entry_map
from miya_server.repositories import authors as authors_repo
from miya_server.repositories import media_items as media_items_repo

_AUTHOR_ITEM_CURSOR_PREFIX = "authoritem"


@strawberry.type
class AuthorItemConnection(relay.Connection[MediaItem]):
    author_id: strawberry.Private[uuid.UUID]

    @strawberry.field
    async def total_count(self, info: strawberry.Info) -> int:
        return await media_items_repo.count_media_items_for_author(
            info.context.session, self.author_id
        )


@strawberry.type
class Author(relay.Node):
    id: relay.NodeID[uuid.UUID]
    slug: str
    name: str

    @strawberry.field
    async def items(
        self,
        info: strawberry.Info,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> AuthorItemConnection:
        """This author's songs and photos across every album, as a forward
        Relay connection keyed on (title, id) -- same contract as Album.items."""
        reject_backward(last, before)
        limit = clamp_first(first)
        after_key = (
            decode_cursor(_AUTHOR_ITEM_CURSOR_PREFIX, after) if after is not None else None
        )
        session = info.context.session

        rows = await media_items_repo.list_media_items_for_author_page(
            session,
            self.id,
            limit=limit + 1,
            after_title=after_key[0] if after_key else None,
            after_id=after_key[1] if after_key else None,
        )
        has_next_page = len(rows) > limit
        page = rows[:limit]

        entry_map = await build_media_entry_map(session, page)
        page = [row for row in page if row.id in entry_map]

        return build_connection(
            AuthorItemConnection,
            page,
            prefix=_AUTHOR_ITEM_CURSOR_PREFIX,
            after=after,
            has_next_page=has_next_page,
            key=lambda row: (row.title, row.id),
            node=lambda row: entry_map[row.id],
            author_id=self.id,
        )

    @classmethod
    async def resolve_nodes(
        cls,
        *,
        info: strawberry.Info,
        node_ids: list[str],
        required: bool = False,
    ) -> list["Author | None"]:
        db_authors = await authors_repo.batch_get_authors(
            info.context.session, [uuid.UUID(nid) for nid in node_ids]
        )
        out: list[Author | None] = []
        for nid, db_author in zip(node_ids, db_authors, strict=True):
            if db_author is None:
                if required:
                    raise ValueError(f"Author with id {nid!r} not found")
                out.append(None)
            else:
                out.append(build_author(db_author))
        return out


def build_author(db_author: DBAuthor) -> Author:
    return Author(id=db_author.id, slug=db_author.slug, name=db_author.name)
