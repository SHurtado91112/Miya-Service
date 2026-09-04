from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import MediaItem, Photo, Song


async def list_media_items_for_album(session: AsyncSession, album_id: UUID) -> list[MediaItem]:
    result = await session.execute(
        select(MediaItem).where(MediaItem.album_id == album_id).order_by(MediaItem.title)
    )
    return list(result.scalars().all())


async def get_songs_map(session: AsyncSession, media_item_ids: list[UUID]) -> dict[UUID, Song]:
    if not media_item_ids:
        return {}
    result = await session.execute(select(Song).where(Song.media_item_id.in_(media_item_ids)))
    return {song.media_item_id: song for song in result.scalars().all()}


async def get_photos_map(session: AsyncSession, media_item_ids: list[UUID]) -> dict[UUID, Photo]:
    if not media_item_ids:
        return {}
    result = await session.execute(select(Photo).where(Photo.media_item_id.in_(media_item_ids)))
    return {photo.media_item_id: photo for photo in result.scalars().all()}
