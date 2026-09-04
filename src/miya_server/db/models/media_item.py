import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miya_server.db.base import Base
from miya_server.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MediaItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Shared base row for songs and photos. `kind` intentionally excludes
    'album' -- a section's mix of media items and album cards is resolved at
    the GraphQL layer (SectionEntry union), not in this table."""

    __tablename__ = "media_items"
    __table_args__ = (CheckConstraint("kind IN ('song', 'photo')", name="media_items_kind_check"),)

    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    subtitle: Mapped[str] = mapped_column(String, nullable=False, default="")
    system_image: Mapped[str] = mapped_column(String, nullable=False, default="")
    detail: Mapped[str] = mapped_column(String, nullable=False, default="")
    primary_media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True
    )
    album_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("albums.id", ondelete="SET NULL"), nullable=True
    )

    primary_media_file = relationship("MediaFile")
    album = relationship("Album", back_populates="items")


class Song(Base):
    """1:1 extension of MediaItem where kind == 'song'."""

    __tablename__ = "songs"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True
    )
    artist: Mapped[str] = mapped_column(String, nullable=False)
    audio_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    media_item = relationship("MediaItem")
    audio_file = relationship("MediaFile")


class Photo(Base):
    """1:1 extension of MediaItem where kind == 'photo'."""

    __tablename__ = "photos"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True
    )
    image_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True
    )
    capture_date: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_make: Mapped[str | None] = mapped_column(String, nullable=True)
    camera_model: Mapped[str | None] = mapped_column(String, nullable=True)
    iso: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aperture: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    shutter_speed: Mapped[str | None] = mapped_column(String, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    media_item = relationship("MediaItem")
    image_file = relationship("MediaFile")
