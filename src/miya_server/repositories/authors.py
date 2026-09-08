from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Album, Author, MediaItem, Section
from miya_server.db.models.associations import section_items


async def get_author_by_slug(session: AsyncSession, slug: str) -> Author | None:
    result = await session.execute(select(Author).where(Author.slug == slug))
    return result.scalar_one_or_none()


async def list_albums_for_author(session: AsyncSession, author_id: UUID) -> list[Album]:
    """Every album that contains at least one item credited to this author,
    ordered by (title, id). Unpaginated -- an author has few albums."""
    stmt = (
        select(Album)
        .join(MediaItem, MediaItem.album_id == Album.id)
        .where(MediaItem.author_id == author_id)
        .order_by(Album.title.asc(), Album.id.asc())
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


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
        .where(or_(Author.name.op("%")(query), Author.name.ilike(f"%{query}%")))
        .order_by(func.similarity(Author.name, query).desc(), Author.id.asc())
        .limit(limit)
    )
    if section_slug is not None:
        # `section_items` is a Home-feed curated pick list, not a section's
        # full domain -- scope by the section's media kind instead, so every
        # author with a song/photo in that domain is eligible, not just ones
        # hand-curated onto the Home feed. See media_items._section_kind_subquery.
        section_kind = (
            select(MediaItem.kind)
            .join(section_items, section_items.c.media_item_id == MediaItem.id)
            .join(Section, Section.id == section_items.c.section_id)
            .where(Section.slug == section_slug)
            .limit(1)
            .scalar_subquery()
        )
        in_section = select(MediaItem.author_id).where(
            MediaItem.author_id.is_not(None), MediaItem.kind == section_kind
        )
        stmt = stmt.where(Author.id.in_(in_section))

    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
