import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable
from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext

from miya_server.auth.errors import AuthError
from miya_server.auth.tokens import verify_access_token
from miya_server.db.base import get_session
from miya_server.db.models import Album, Author, User
from miya_server.repositories import users as users_repo
from miya_server.repositories.albums import batch_get_albums
from miya_server.repositories.authors import batch_get_authors


class SerializedSession:
    """Wraps an AsyncSession so concurrent GraphQL field resolvers sharing one
    request-scoped session don't issue overlapping statements on the same
    asyncpg connection -- GraphQL-core resolves sibling fields concurrently
    by default via asyncio.gather, which otherwise raises
    'cannot perform operation: another operation is in progress'."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._lock = asyncio.Lock()

    async def execute(self, statement: Executable, *args: Any, **kwargs: Any) -> Result:
        async with self._lock:
            return await self._session.execute(statement, *args, **kwargs)

    def add(self, instance: object) -> None:
        """Sync and connection-free -- it only stages the object in the identity
        map -- so it needs no lock."""
        self._session.add(instance)

    async def flush(self) -> None:
        async with self._lock:
            await self._session.flush()

    async def commit(self) -> None:
        async with self._lock:
            await self._session.commit()

    async def rollback(self) -> None:
        async with self._lock:
            await self._session.rollback()


@dataclass
class GraphQLContext(BaseContext):
    session: SerializedSession
    album_loader: DataLoader[UUID, Album | None]
    author_loader: DataLoader[UUID, Author | None]
    #: Resolved once per request in `get_context`, before any field runs.
    #: Eager rather than lazy so `IsAuthenticated.has_permission` can be
    #: *synchronous*: Strawberry picks the sync extension chain for any field
    #: whose resolver is sync -- `relay.node()`'s is -- and a coroutine returned
    #: into that chain is never awaited, which silently passes the permission
    #: check and then fails as "Abstract type 'Node' must resolve to an Object
    #: type". One indexed lookup per authenticated request is a fair price.
    viewer: User | None = None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def _resolve_viewer(request: Request, session: SerializedSession) -> User | None:
    token = _bearer_token(request)
    if token is None:
        return None
    try:
        user_id = verify_access_token(token)
    except AuthError:
        return None
    return await users_repo.get_user(session, user_id)


async def get_context(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> GraphQLContext:
    serialized_session = SerializedSession(session)
    return GraphQLContext(
        session=serialized_session,
        album_loader=DataLoader(load_fn=lambda ids: batch_get_albums(serialized_session, ids)),
        author_loader=DataLoader(load_fn=lambda ids: batch_get_authors(serialized_session, ids)),
        viewer=await _resolve_viewer(request, serialized_session),
    )
