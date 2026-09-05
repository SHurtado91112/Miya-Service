from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miya_server.db.base import Base
from miya_server.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Author(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person credited on media items -- a musical artist for songs, a
    photographer for photos. `slug` is the stable human id the iOS client uses
    as its domain id; `id` is the opaque Relay global id used by `node(id:)`
    and `Author.items`.

    There is deliberately no `kind` column: an author is just a name, and
    `Author.items` returns whatever media items point at them regardless of
    kind. Album authorship is not modelled yet (albums have no `author_id`).
    """

    __tablename__ = "authors"
    __table_args__ = (Index("ix_authors_name_id", "name", "id"),)

    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    items = relationship("MediaItem", back_populates="author")
