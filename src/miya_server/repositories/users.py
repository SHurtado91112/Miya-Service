from uuid import UUID

from sqlalchemy import select

from miya_server.auth.google import GoogleIdentity
from miya_server.db.models import User


async def get_user(session, user_id: UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def upsert_from_google(session, identity: GoogleIdentity) -> User:
    """Find the user behind a verified Google identity, creating them on first
    sign-in. Matched on `google_sub` only -- see the note on `User`."""
    result = await session.execute(select(User).where(User.google_sub == identity.sub))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            google_sub=identity.sub,
            email=identity.email,
            name=identity.name,
            avatar_url=identity.avatar_url,
        )
        session.add(user)
    else:
        # Refresh the cached profile: people rename themselves and change
        # avatars, and a stale display name is the kind of thing users notice.
        user.email = identity.email
        user.name = identity.name
        user.avatar_url = identity.avatar_url

    await session.flush()
    return user
