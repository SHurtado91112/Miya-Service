"""Miya's own credentials: a short-lived access JWT and a long-lived, rotating
refresh token.

Two different kinds of secret, on purpose:

* The **access token** is a signed JWT. It is verified with a signature check
  alone -- no database round trip -- so it must be short-lived, because there is
  no way to revoke one before it expires.
* The **refresh token** is opaque randomness with a database row behind it. It
  can be revoked instantly, and it is single-use: redeeming one issues a
  successor and burns the original.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select, update

from miya_server.auth.errors import AuthError
from miya_server.config import get_settings
from miya_server.db.models import RefreshToken, User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def mint_access_token(user_id: uuid.UUID) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": expires_at},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    return token, expires_at


def verify_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return uuid.UUID(claims["sub"])
    except Exception as exc:
        raise AuthError("Invalid or expired access token.") from exc


def _hash(raw_token: str) -> str:
    """SHA-256, not a password hash.

    Refresh tokens are 256 bits of `secrets` randomness, so there is no
    dictionary to attack and nothing for bcrypt's work factor to buy. Plain
    SHA-256 keeps verification a single indexed lookup.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def issue_refresh_token(session, user_id: uuid.UUID) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    row = RefreshToken(
        user_id=user_id,
        token_hash=_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(row)
    await session.flush()
    # The raw value exists only in this return -- the database keeps the hash.
    return raw


async def _revoke_chain(session, token: RefreshToken) -> None:
    """Revoke every unrevoked token belonging to this user.

    Reached only on reuse of an already-redeemed token, which means the token
    leaked: either an attacker is replaying a stolen token, or the legitimate
    client is replaying one an attacker already spent. Nothing distinguishes
    those two cases from here, so both end the same way -- everything dies and
    the real user signs in again.
    """
    logger.warning(
        "Refresh token reuse detected for user %s; revoking all sessions", token.user_id
    )
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    # Commit here, not in the resolver. The caller raises immediately after
    # this returns, so the resolver never reaches its own commit -- without
    # this the revocation rolls back with the failed request and the leaked
    # token family stays live, which defeats the entire mechanism.
    await session.commit()


async def redeem_refresh_token(session, raw_token: str) -> tuple[User, str]:
    """Validate a refresh token and rotate it, returning its owner and the
    replacement. Raises `AuthError` for anything unusable."""
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(raw_token))
    )
    token = result.scalar_one_or_none()
    if token is None:
        raise AuthError("Invalid refresh token.")

    if token.revoked_at is not None:
        await _revoke_chain(session, token)
        raise AuthError("Invalid refresh token.")

    # `expires_at` comes back tz-aware from a timestamptz column; be explicit
    # anyway so a naive value from a differently-configured driver can't make
    # this comparison throw.
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise AuthError("Refresh token has expired.")

    user_result = await session.execute(select(User).where(User.id == token.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise AuthError("Invalid refresh token.")

    replacement = await issue_refresh_token(session, user.id)
    replacement_result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(replacement))
    )
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replacement_result.scalar_one().id
    await session.flush()

    return user, replacement


async def revoke_refresh_token(session, raw_token: str) -> bool:
    """Sign-out. Idempotent: revoking an unknown or already-revoked token
    reports success, since the caller's goal -- that token being unusable -- is
    satisfied either way."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash(raw_token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return True
