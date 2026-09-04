from uuid import UUID

import strawberry

from miya_server.db.models import Album as DBAlbum
from miya_server.graphql.types.media_item import MediaItem, build_media_entries
from miya_server.media.storage import build_media_url
from miya_server.repositories import media_items as media_items_repo


@strawberry.type
class Album:
    id: strawberry.ID
    slug: str
    title: str
    subtitle: str
    system_image: str
    image_url: str | None
    _id: strawberry.Private[UUID]

    @strawberry.field
    async def items(self, info: strawberry.Info) -> list[MediaItem]:
        db_items = await media_items_repo.list_media_items_for_album(info.context.session, self._id)
        return await build_media_entries(info.context.session, db_items)


def build_album(db_album: DBAlbum) -> Album:
    return Album(
        id=strawberry.ID(str(db_album.id)),
        slug=db_album.slug,
        title=db_album.title,
        subtitle=db_album.subtitle,
        system_image=db_album.system_image,
        image_url=build_media_url(db_album.cover_media_file_id),
        _id=db_album.id,
    )
