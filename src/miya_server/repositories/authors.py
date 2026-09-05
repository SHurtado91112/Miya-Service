from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Author, MediaItem, Section
from miya_server.db.models.associations import section_items


async def get_author_by_slug(session: AsyncSession, slug: str) -> Author | None:
    result = await session.execute(select(Author).where(Author.slug == slug))
    return result.scalar_one_or_none()


async def batch_get_authors(session: AsyncSession, ids: list[UUID]) -> list[Author | None]:
    """Order-preserving batch fetch for the DataLoader and relay Node resolution
    -- one entry (or None) per id, in the same order as `ids`."""
    if not ids:
        return []
    result = await session.execute(select(Author).where(Author.id.in_(ids)))
    by_id = {author.id: author for author in result.scalars().all()}
    return [by_id.get(author_id) for author_id in ids]


async def search_authors(
    session: AsyncSession,
    query: str,
    *,
    section_slug: str | None = None,
    limit: int = 10,
) -> list[Author]:
    """Fuzzy match on `authors.name` via the pg_trgm GIN index, ranked by
    similarity. When `section_slug` is given, restrict to authors that credit
    at least one media item in that section."""
    query = query.strip()
    if not query:
        return []

    stmt = (
        select(Author)
        .where(Author.name.op("%")(query))
        .order_by(func.similarity(Author.name, query).desc(), Author.id.asc())
        .limit(limit)
    )
    if section_slug is not None:
        in_section = (
            select(MediaItem.author_id)
            .join(section_items, section_items.c.media_item_id == MediaItem.id)
            .join(Section, Section.id == section_items.c.section_id)
            .where(Section.slug == section_slug, MediaItem.author_id.is_not(None))
        )
        stmt = stmt.where(Author.id.in_(in_section))

    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
