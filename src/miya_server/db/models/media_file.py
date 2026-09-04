from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from miya_server.db.base import Base
from miya_server.db.models.mixins import UUIDPrimaryKeyMixin


class MediaFile(UUIDPrimaryKeyMixin, Base):
    """Metadata for a file stored on disk under MEDIA_ROOT. The row's id is used
    as the on-disk filename stem, decoupling storage naming from display titles."""

    __tablename__ = "media_files"

    relative_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
