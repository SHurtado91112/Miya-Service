import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miya_server.db.base import Base
from miya_server.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Album(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "albums"

    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    subtitle: Mapped[str] = mapped_column(String, nullable=False, default="")
    system_image: Mapped[str] = mapped_column(String, nullable=False, default="")
    cover_media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True
    )

    cover_media_file = relationship("MediaFile")
    items = relationship(
        "MediaItem", back_populates="album", order_by="MediaItem.title"
    )
