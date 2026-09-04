from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from miya_server.db.base import Base
from miya_server.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Section(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sections"

    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
