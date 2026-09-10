import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miya_server.db.base import Base
from miya_server.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Someone who can sign in to Miya.

    Identity is keyed on `google_sub` -- the `sub` claim of Google's id_token --
    not on email. Google explicitly documents `sub` as the only stable, unique
    per-account identifier: an email address can be changed by its owner, and a
    Workspace address can be deleted and later reissued to a different person.
    Matching on email would silently hand the second person the first person's
    library.

    `email`/`name`/`avatar_url` are cached profile fields, refreshed on every
    sign-in. They are display data only and are never used to look a user up.
    """

    __tablename__ = "users"

    google_sub: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One issued refresh token, stored only as a SHA-256 hash.

    The raw token is high-entropy random and is shown to the client exactly
    once; a database leak therefore yields no usable credentials. Tokens are
    single-use and rotated: redeeming one revokes it and issues a successor,
    linked through `replaced_by_id`.

    That chain is what makes theft detectable. If a revoked token is presented
    again, either the legitimate client or an attacker is replaying it -- we
    cannot tell which, so `revoke_chain` kills the entire family and forces a
    fresh sign-in. This is the reuse-detection scheme from OAuth 2.0 BCP
    (RFC 9700 section 4.14.2).
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    user = relationship("User", back_populates="refresh_tokens")
