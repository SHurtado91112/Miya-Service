"""enable pg_trgm and add trigram search indexes

Revision ID: 76820e592aee
Revises: f26837c38f48
Create Date: 2026-09-04

"""

from collections.abc import Sequence

from alembic import op

revision: str = "76820e592aee"
down_revision: str | None = "f26837c38f48"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_media_items_title_trgm ON media_items USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_media_items_subtitle_trgm ON media_items USING gin (subtitle gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_songs_artist_trgm ON songs USING gin (artist gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_songs_artist_trgm")
    op.execute("DROP INDEX IF EXISTS ix_media_items_subtitle_trgm")
    op.execute("DROP INDEX IF EXISTS ix_media_items_title_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
