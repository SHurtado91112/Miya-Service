"""composite btree indexes for keyset pagination

Revision ID: 9b2e4c7a1f38
Revises: 76820e592aee
Create Date: 2026-09-05

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b2e4c7a1f38"
down_revision: str | None = "76820e592aee"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_albums_title_id", "albums", ["title", "id"], unique=False)
    op.create_index(
        "ix_media_items_album_id_title_id",
        "media_items",
        ["album_id", "title", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_media_items_album_id_title_id", table_name="media_items")
    op.drop_index("ix_albums_title_id", table_name="albums")
