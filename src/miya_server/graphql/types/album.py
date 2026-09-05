import uuid

import strawberry
from strawberry import relay

from miya_server.db.models import Album as DBAlbum
from miya_server.graphql.pagination import (
    build_connection,
    clamp_first,
    decode_cursor,
    reject_backward,
)
from miya_server.graphql.types.media_item import (
    MediaItemConnection,
    build_media_entry_map,
)
from miya_server.media.storage import build_media_url
from miya_server.repositories import albums as albums_repo
from miya_server.repositories import media_items as media_items_repo

_ITEM_CURSOR_PREFIX = "mediaitem"


@strawberry.type
class Album(relay.Node):
    id: relay.NodeID[uuid.UUID]
    slug: str
    title: str
    subtitle: str
    system_image: str
    image_url: str | None

    @strawberry.field
    async def items(
        self,
        info: strawberry.Info,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> MediaItemConnection:
        reject_backward(last, before)
        limit = clamp_first(first)
        after_key = decode_cursor(_ITEM_CURSOR_PREFIX, after) if after is not None else None
        session = info.context.session

        rows = await media_items_repo.list_media_items_for_album_page(
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
            MediaItemConnection,
            page,
            prefix=_ITEM_CURSOR_PREFIX,
            after=after,
            has_next_page=has_next_page,
            key=lambda row: (row.title, row.id),
            node=lambda row: entry_map[row.id],
            album_id=self.id,
        )

    @classmethod
    async def resolve_nodes(
        cls,
        *,
        info: strawberry.Info,
        node_ids: list[str],
        required: bool = False,
    ) -> list["Album | None"]:
        db_albums = await albums_repo.batch_get_albums(
            info.context.session, [uuid.UUID(nid) for nid in node_ids]
        )
        out: list[Album | None] = []
        for nid, db_album in zip(node_ids, db_albums, strict=True):
            if db_album is None:
                if required:
                    raise ValueError(f"Album with id {nid!r} not found")
                out.append(None)
            else:
                out.append(build_album(db_album))
        return out


@strawberry.type
class AlbumConnection(relay.Connection[Album]):
    @strawberry.field
    async def total_count(self, info: strawberry.Info) -> int:
        return await albums_repo.count_albums(info.context.session)


def build_album(db_album: DBAlbum) -> Album:
    return Album(
        id=db_album.id,
        slug=db_album.slug,
        title=db_album.title,
        subtitle=db_album.subtitle,
        system_image=db_album.system_image,
        image_url=build_media_url(db_album.cover_media_file_id),
    )
