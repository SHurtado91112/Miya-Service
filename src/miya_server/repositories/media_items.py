from uuid import UUID

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import MediaItem, Photo, Song


async def list_media_items_for_album_page(
    session: AsyncSession,
    album_id: UUID,
    *,
    limit: int,
    after_title: str | None = None,
    after_id: UUID | None = None,
) -> list[MediaItem]:
    """One keyset page of an album's items ordered by (title, id)."""
    stmt = (
        select(MediaItem)
        .where(MediaItem.album_id == album_id)
        .order_by(MediaItem.title.asc(), MediaItem.id.asc())
        .limit(limit)
    )
    if after_title is not None and after_id is not None:
        stmt = stmt.where(tuple_(MediaItem.title, MediaItem.id) > (after_title, after_id))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_media_items_for_album(session: AsyncSession, album_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(MediaItem).where(MediaItem.album_id == album_id)
    )
    return int(result.scalar_one())


async def batch_get_media_items(
    session: AsyncSession, ids: list[UUID]
) -> list[MediaItem | None]:
    """Order-preserving batch fetch for relay Node resolution."""
    result = await session.execute(select(MediaItem).where(MediaItem.id.in_(ids)))
    by_id = {item.id: item for item in result.scalars().all()}
    return [by_id.get(item_id) for item_id in ids]


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
