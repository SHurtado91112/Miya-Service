from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.config import get_settings
from miya_server.db.base import get_session
from miya_server.db.models import MediaFile

router = APIRouter()


_IMMUTABLE_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/{file_id}")
async def get_media_file(
    file_id: UUID, session: AsyncSession = Depends(get_session)  # noqa: B008
) -> FileResponse:
    result = await session.execute(select(MediaFile).where(MediaFile.id == file_id))
    media_file = result.scalar_one_or_none()
    if media_file is None:
        raise HTTPException(status_code=404, detail="Media file not found")

    settings = get_settings()
    path = settings.media_root / media_file.relative_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file missing on disk")

    return FileResponse(
        path,
        media_type=media_file.mime_type,
        # Content is immutable once ingested -- a changed file gets a new
        # media_files.id, never overwritten in place -- so cache forever.
        headers=_IMMUTABLE_CACHE,
    )


@router.get("/{file_id}/thumb")
async def get_media_thumbnail(
    file_id: UUID, session: AsyncSession = Depends(get_session)  # noqa: B008
) -> FileResponse:
    """The generated WebP thumbnail for an image. Falls back to the original
    bytes when a row has no thumbnail yet (pre-feature rows before
    `backfill-thumbnails` runs, or a source Pillow couldn't decode) so a
    `thumbnailUrl` handed to a client is never a broken link."""
    result = await session.execute(select(MediaFile).where(MediaFile.id == file_id))
    media_file = result.scalar_one_or_none()
    if media_file is None:
        raise HTTPException(status_code=404, detail="Media file not found")

    has_thumb = media_file.thumbnail_relative_path is not None
    relative_path = media_file.thumbnail_relative_path if has_thumb else media_file.relative_path
    media_type = media_file.thumbnail_mime_type if has_thumb else media_file.mime_type

    settings = get_settings()
    path = settings.media_root / relative_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file missing on disk")

    return FileResponse(path, media_type=media_type, headers=_IMMUTABLE_CACHE)
