from uuid import UUID

from sqlalchemy import func, or_, select
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


async def search_media_items(session: AsyncSession, query: str, limit: int = 20) -> list[MediaItem]:
    """Fuzzy/typo-tolerant search over title, subtitle, and (for songs) artist,
    backed by the pg_trgm GIN indexes -- the `%` operator applies pg_trgm's
    default similarity threshold (0.3), and results are ranked by best match."""
    query = query.strip()
    if not query:
        return []

    best_similarity = func.greatest(
        func.similarity(MediaItem.title, query),
        func.similarity(MediaItem.subtitle, query),
        func.similarity(func.coalesce(Song.artist, ""), query),
    )
    stmt = (
        select(MediaItem)
        .outerjoin(Song, Song.media_item_id == MediaItem.id)
        .where(
            or_(
                MediaItem.title.op("%")(query),
                MediaItem.subtitle.op("%")(query),
                Song.artist.op("%")(query),
            )
        )
        .order_by(best_similarity.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
