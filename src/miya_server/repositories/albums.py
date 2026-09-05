from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Album


async def list_albums_page(
    session: AsyncSession,
    *,
    limit: int,
    after_title: str | None = None,
    after_id: UUID | None = None,
) -> list[Album]:
    """One keyset page of albums ordered by (title, id). Pass `after_title` /
    `after_id` (the sort key of the last row of the previous page) to get the
    next page. `id` is the tiebreaker -- album titles are not unique."""
    stmt = select(Album).order_by(Album.title.asc(), Album.id.asc()).limit(limit)
    if after_title is not None and after_id is not None:
        stmt = stmt.where(tuple_(Album.title, Album.id) > (after_title, after_id))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_albums(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Album))
    return int(result.scalar_one())


async def get_album_by_slug(session: AsyncSession, slug: str) -> Album | None:
    result = await session.execute(select(Album).where(Album.slug == slug))
    return result.scalar_one_or_none()


async def batch_get_albums(session: AsyncSession, ids: list[UUID]) -> list[Album | None]:
    """Batch loader for strawberry.dataloader.DataLoader and relay Node
    resolution -- must return results in the same order as `ids`, one entry
    (or None) per id."""
    result = await session.execute(select(Album).where(Album.id.in_(ids)))
    by_id = {album.id: album for album in result.scalars().all()}
    return [by_id.get(album_id) for album_id in ids]
