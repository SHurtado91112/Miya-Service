"""add authors table + media_items.author_id + trgm indexes

Revision ID: a1b2c3d4e5f6
Revises: 9b2e4c7a1f38
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9b2e4c7a1f38"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_authors_name_id", "authors", ["name", "id"], unique=False)

    op.add_column(
        "media_items",
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "media_items_author_id_fkey",
        "media_items",
        "authors",
        ["author_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_media_items_author_id_title_id",
        "media_items",
        ["author_id", "title", "id"],
        unique=False,
    )

    # pg_trgm was enabled in 76820e592aee. Extend fuzzy search to author names
    # and album titles/subtitles (the search() union matches on parent-album
    # title and on album cards directly).
    op.execute("CREATE INDEX ix_authors_name_trgm ON authors USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_albums_title_trgm ON albums USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX ix_albums_subtitle_trgm ON albums USING gin (subtitle gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_albums_subtitle_trgm")
    op.execute("DROP INDEX IF EXISTS ix_albums_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_authors_name_trgm")
    op.drop_index("ix_media_items_author_id_title_id", table_name="media_items")
    op.drop_constraint("media_items_author_id_fkey", "media_items", type_="foreignkey")
    op.drop_column("media_items", "author_id")
    op.drop_index("ix_authors_name_id", table_name="authors")
    op.drop_table("authors")
