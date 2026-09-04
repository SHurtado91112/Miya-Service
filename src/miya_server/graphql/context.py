import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable
from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext

from miya_server.db.base import get_session
from miya_server.db.models import Album
from miya_server.repositories.albums import batch_get_albums


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


@dataclass
class GraphQLContext(BaseContext):
    session: SerializedSession
    album_loader: DataLoader[UUID, Album | None]


async def get_context(session: AsyncSession = Depends(get_session)) -> GraphQLContext:  # noqa: B008
    serialized_session = SerializedSession(session)
    return GraphQLContext(
        session=serialized_session,
        album_loader=DataLoader(load_fn=lambda ids: batch_get_albums(serialized_session, ids)),
    )
