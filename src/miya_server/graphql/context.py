from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader

from miya_server.db.base import get_session
from miya_server.db.models import Album
from miya_server.repositories.albums import batch_get_albums


@dataclass
class GraphQLContext:
    session: AsyncSession
    album_loader: DataLoader[UUID, Album | None]


async def get_context(session: AsyncSession = Depends(get_session)) -> GraphQLContext:  # noqa: B008
    return GraphQLContext(
        session=session,
        album_loader=DataLoader(load_fn=lambda ids: batch_get_albums(session, ids)),
    )
