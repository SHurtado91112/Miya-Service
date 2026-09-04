from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Album


async def list_albums(session: AsyncSession) -> list[Album]:
    result = await session.execute(select(Album).order_by(Album.title))
    return list(result.scalars().all())


async def get_album_by_slug(session: AsyncSession, slug: str) -> Album | None:
    result = await session.execute(select(Album).where(Album.slug == slug))
    return result.scalar_one_or_none()


async def batch_get_albums(session: AsyncSession, ids: list[UUID]) -> list[Album | None]:
    """Batch loader for strawberry.dataloader.DataLoader -- must return results
    in the same order as `ids`, one entry (or None) per id."""
    result = await session.execute(select(Album).where(Album.id.in_(ids)))
    by_id = {album.id: album for album in result.scalars().all()}
    return [by_id.get(album_id) for album_id in ids]
