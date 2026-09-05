from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from miya_server.db.models import Album, MediaItem, Photo, Section, Song
from miya_server.db.models.associations import section_albums, section_items


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


async def list_media_items_for_author_page(
    session: AsyncSession,
    author_id: UUID,
    *,
    limit: int,
    after_title: str | None = None,
    after_id: UUID | None = None,
) -> list[MediaItem]:
    """One keyset page of an author's items ordered by (title, id) -- the
    author's songs and photos across every album, backed by
    ix_media_items_author_id_title_id."""
    stmt = (
        select(MediaItem)
        .where(MediaItem.author_id == author_id)
        .order_by(MediaItem.title.asc(), MediaItem.id.asc())
        .limit(limit)
    )
    if after_title is not None and after_id is not None:
        stmt = stmt.where(tuple_(MediaItem.title, MediaItem.id) > (after_title, after_id))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_media_items_for_author(session: AsyncSession, author_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(MediaItem).where(MediaItem.author_id == author_id)
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


# MARK: - Search


@dataclass
class SearchEntryRow:
    """One row of a search results page -- a pointer, hydrated to a full
    Song/Photo/Album by the resolver. `row_kind` says which table `id` is in;
    `score` is the pg_trgm similarity used for relevance ordering."""

    row_kind: Literal["media_item", "album"]
    id: UUID
    title: str
    score: float


def _matched_album_ids(query: str, section_slug: str | None):
    """SELECT of album ids whose title/subtitle match `query` (optionally scoped
    to a section's album cards). Drives the album branch of the search union and
    the folding exclusion on the media branch."""
    stmt = select(Album.id).where(
        or_(Album.title.op("%")(query), Album.subtitle.op("%")(query))
    )
    if section_slug is not None:
        stmt = stmt.where(
            Album.id.in_(
                select(section_albums.c.album_id)
                .join(Section, Section.id == section_albums.c.section_id)
                .where(Section.slug == section_slug)
            )
        )
    return stmt


def _search_union(query: str, section_slug: str | None):
    """SELECT of `(row_kind, id, title, score)` for every media item or album
    matching `query` on title / subtitle / (song) artist / parent-album title,
    via the pg_trgm `%` operator. `score` is the best per-row trigram
    similarity. Optionally scoped to one section's membership.

    Album members are folded away: a media item whose parent album is itself a
    match is excluded, so the album row stands in for it."""
    parent_album = aliased(Album)

    media_score = func.greatest(
        func.similarity(MediaItem.title, query),
        func.similarity(MediaItem.subtitle, query),
        func.similarity(func.coalesce(Song.artist, ""), query),
        func.similarity(func.coalesce(parent_album.title, ""), query),
    )
    media_items_q = (
        select(
            literal("media_item").label("row_kind"),
            MediaItem.id.label("id"),
            MediaItem.title.label("title"),
            media_score.label("score"),
        )
        .select_from(MediaItem)
        .outerjoin(Song, Song.media_item_id == MediaItem.id)
        .outerjoin(parent_album, parent_album.id == MediaItem.album_id)
        .where(
            or_(
                MediaItem.title.op("%")(query),
                MediaItem.subtitle.op("%")(query),
                Song.artist.op("%")(query),
                parent_album.title.op("%")(query),
            )
        )
        .where(
            or_(
                MediaItem.album_id.is_(None),
                MediaItem.album_id.not_in(_matched_album_ids(query, section_slug)),
            )
        )
    )

    album_score = func.greatest(
        func.similarity(Album.title, query),
        func.similarity(Album.subtitle, query),
    )
    albums_q = select(
        literal("album").label("row_kind"),
        Album.id.label("id"),
        Album.title.label("title"),
        album_score.label("score"),
    ).where(Album.id.in_(_matched_album_ids(query, section_slug)))

    if section_slug is not None:
        media_items_q = media_items_q.where(
            MediaItem.id.in_(
                select(section_items.c.media_item_id)
                .join(Section, Section.id == section_items.c.section_id)
                .where(Section.slug == section_slug)
            )
        )

    return media_items_q.union_all(albums_q)


async def search_section_entries_page(
    session: AsyncSession,
    query: str,
    *,
    section_slug: str | None = None,
    limit: int,
    after_score: float | None = None,
    after_id: UUID | None = None,
) -> list[SearchEntryRow]:
    """One page of search results ordered by (score DESC, id ASC) -- relevance
    first, `id` as the stable tiebreaker so forward cursor pagination is
    gap-free. Blank query -> no results."""
    query = query.strip()
    if not query:
        return []

    union_sq = _search_union(query, section_slug).subquery()
    score_col = union_sq.c.score
    id_col = union_sq.c.id
    stmt = (
        select(union_sq.c.row_kind, id_col, union_sq.c.title, score_col)
        .order_by(score_col.desc(), id_col.asc())
        .limit(limit)
    )
    if after_score is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                score_col < after_score,
                and_(score_col == after_score, id_col > after_id),
            )
        )

    rows = (await session.execute(stmt)).all()
    return [
        SearchEntryRow(row_kind=row.row_kind, id=row.id, title=row.title, score=float(row.score))
        for row in rows
    ]


async def count_search_section_entries(
    session: AsyncSession, query: str, *, section_slug: str | None = None
) -> int:
    query = query.strip()
    if not query:
        return 0
    union_sq = _search_union(query, section_slug).subquery()
    result = await session.execute(select(func.count()).select_from(union_sq))
    return int(result.scalar_one())
