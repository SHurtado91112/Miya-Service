from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.dialects.postgresql import UUID

from miya_server.db.base import Base

section_items = Table(
    "section_items",
    Base.metadata,
    Column("section_id", UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
    Column("media_item_id", UUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True),
    Column("sort_order", Integer, nullable=False, default=0),
)

section_albums = Table(
    "section_albums",
    Base.metadata,
    Column("section_id", UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
    Column("album_id", UUID(as_uuid=True), ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True),
    Column("sort_order", Integer, nullable=False, default=0),
)
