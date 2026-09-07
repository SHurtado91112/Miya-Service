"""add media_files thumbnail columns + authors.profile_media_file_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-07

Thumbnails are stored as extra columns on the existing media_files row (a
generated WebP derivative on disk next to the original), not as their own row.
Author portraits reuse the media_files/ingest machinery via a single nullable
FK, mirroring albums.cover_media_file_id.

Existing media_files rows are backfilled by the `backfill-thumbnails` CLI, not
here -- generating derivatives needs filesystem + PIL access to MEDIA_ROOT.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_files", sa.Column("thumbnail_relative_path", sa.String(), nullable=True))
    op.create_unique_constraint(
        "media_files_thumbnail_relative_path_key",
        "media_files",
        ["thumbnail_relative_path"],
    )
    op.add_column("media_files", sa.Column("thumbnail_width", sa.Integer(), nullable=True))
    op.add_column("media_files", sa.Column("thumbnail_height", sa.Integer(), nullable=True))
    op.add_column("media_files", sa.Column("thumbnail_mime_type", sa.String(), nullable=True))

    op.add_column(
        "authors",
        sa.Column("profile_media_file_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "authors_profile_media_file_id_fkey",
        "authors",
        "media_files",
        ["profile_media_file_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("authors_profile_media_file_id_fkey", "authors", type_="foreignkey")
    op.drop_column("authors", "profile_media_file_id")

    op.drop_column("media_files", "thumbnail_mime_type")
    op.drop_column("media_files", "thumbnail_height")
    op.drop_column("media_files", "thumbnail_width")
    op.drop_constraint("media_files_thumbnail_relative_path_key", "media_files", type_="unique")
    op.drop_column("media_files", "thumbnail_relative_path")
