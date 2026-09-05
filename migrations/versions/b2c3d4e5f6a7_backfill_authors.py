"""backfill authors from song artists + a synthetic photographer for photos

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05

One-time data migration for an already-populated database. The durable path is
`seed_data.py` / `bulk_generate.py`, which create the same rows on a fresh DB;
this backfills a DB that was seeded before authors existed.

- Every distinct non-blank `songs.artist` becomes an `authors` row
  (slug = slugify(name)); its songs get `media_items.author_id`.
- Every photo with no author is credited to one synthetic photographer,
  slug `steven-hurtado` (kept in sync with seed/authors.py).
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

PHOTOGRAPHER_SLUG = "steven-hurtado"
PHOTOGRAPHER_NAME = "Steven Hurtado"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


def upgrade() -> None:
    conn = op.get_bind()

    artists = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT DISTINCT artist FROM songs WHERE artist <> ''")
        )
    ]

    used_slugs: dict[str, str] = {}
    for artist in sorted(artists):
        slug = _slugify(artist)
        base, n = slug, 2
        while slug in used_slugs and used_slugs[slug] != artist:
            slug, n = f"{base}-{n}", n + 1
        used_slugs[slug] = artist
        conn.execute(
            sa.text(
                "INSERT INTO authors (slug, name) VALUES (:slug, :name) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"slug": slug, "name": artist},
        )

    conn.execute(
        sa.text(
            "UPDATE media_items mi SET author_id = a.id "
            "FROM songs s JOIN authors a ON a.name = s.artist "
            "WHERE s.media_item_id = mi.id AND mi.author_id IS NULL"
        )
    )

    conn.execute(
        sa.text(
            "INSERT INTO authors (slug, name) VALUES (:slug, :name) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": PHOTOGRAPHER_SLUG, "name": PHOTOGRAPHER_NAME},
    )
    conn.execute(
        sa.text(
            "UPDATE media_items SET author_id = "
            "(SELECT id FROM authors WHERE slug = :slug) "
            "WHERE kind = 'photo' AND author_id IS NULL"
        ),
        {"slug": PHOTOGRAPHER_SLUG},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE media_items SET author_id = NULL"))
    conn.execute(sa.text("DELETE FROM authors"))
