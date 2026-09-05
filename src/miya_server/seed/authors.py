"""Shared helpers for creating/linking `authors` rows from the seed and the
bulk generator. Keeps slug derivation identical across both so re-running
either is idempotent and they never fight over the same author.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.models import Author

# Every seeded/bulk photo is credited to this single synthetic photographer --
# the source fixtures carry no per-photo photographer, so this gives the photo
# author-search / author-drilldown something real to resolve. Kept in sync with
# the backfill migration.
PHOTOGRAPHER_SLUG = "steven-hurtado"
PHOTOGRAPHER_NAME = "Steven Hurtado"


def slugify(name: str) -> str:
    """Lowercase, non-alphanumeric runs -> single hyphen, trimmed. Matches the
    slug scheme the backfill migration uses."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


async def get_or_create_author(session: AsyncSession, name: str) -> Author | None:
    """Upsert an author by slug(name). Returns None for a blank name so callers
    can leave `author_id` NULL."""
    name = (name or "").strip()
    if not name:
        return None
    slug = slugify(name)
    author = (
        await session.execute(select(Author).where(Author.slug == slug))
    ).scalar_one_or_none()
    if author is None:
        author = Author(slug=slug, name=name)
        session.add(author)
        await session.flush()
    elif author.name != name:
        author.name = name
    return author


async def get_or_create_photographer(session: AsyncSession) -> Author:
    author = (
        await session.execute(select(Author).where(Author.slug == PHOTOGRAPHER_SLUG))
    ).scalar_one_or_none()
    if author is None:
        author = Author(slug=PHOTOGRAPHER_SLUG, name=PHOTOGRAPHER_NAME)
        session.add(author)
        await session.flush()
    return author
