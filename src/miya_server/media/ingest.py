"""Local ingest CLI: matches files under a directory to existing media_items
(by slug == filename stem) or albums (for cover art), copies them into
MEDIA_ROOT, creates media_files rows, and backfills the FKs
(media_items.primary_media_file_id, songs.audio_file_id, photos.image_file_id,
albums.cover_media_file_id).

Content is addressed by checksum -- re-ingesting an unchanged file is a no-op;
a changed file gets a new media_files row rather than overwriting in place.

Run via: uv run ingest-media --dir /path/to/local/media
"""

import argparse
import asyncio
import hashlib
import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.config import get_settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import Album, MediaFile, MediaItem, Photo, Song

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".aac"}

try:
    from PIL import Image
except ImportError:
    Image = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    if Image is None:
        return None, None
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:  # noqa: BLE001 -- best-effort metadata, never fail ingest over it
        return None, None


async def _get_or_create_media_file(session: AsyncSession, source: Path, subdir: str) -> MediaFile:
    checksum = _sha256(source)
    existing = (
        await session.execute(select(MediaFile).where(MediaFile.checksum_sha256 == checksum))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    settings = get_settings()
    mime_type, _ = mimetypes.guess_type(source.name)
    mime_type = mime_type or "application/octet-stream"
    file_id = uuid4()
    dest_relative = f"{subdir}/{file_id}{source.suffix.lower()}"
    dest_path = settings.media_root / dest_relative
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest_path)

    width = height = None
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        width, height = _image_dimensions(dest_path)

    media_file = MediaFile(
        id=file_id,
        relative_path=dest_relative,
        mime_type=mime_type,
        size_bytes=dest_path.stat().st_size,
        width=width,
        height=height,
        checksum_sha256=checksum,
    )
    session.add(media_file)
    await session.flush()
    return media_file


async def _ingest_file(session: AsyncSession, source: Path) -> str:
    stem = source.stem
    ext = source.suffix.lower()

    item = (await session.execute(select(MediaItem).where(MediaItem.slug == stem))).scalar_one_or_none()
    if item is not None:
        if ext in AUDIO_EXTENSIONS and item.kind == "song":
            media_file = await _get_or_create_media_file(session, source, "songs")
            song = (
                await session.execute(select(Song).where(Song.media_item_id == item.id))
            ).scalar_one_or_none()
            if song is not None:
                song.audio_file_id = media_file.id
            return f"linked audio -> song '{stem}'"

        if ext in IMAGE_EXTENSIONS:
            subdir = "photos" if item.kind == "photo" else "songs"
            media_file = await _get_or_create_media_file(session, source, subdir)
            item.primary_media_file_id = media_file.id
            if item.kind == "photo":
                photo = (
                    await session.execute(select(Photo).where(Photo.media_item_id == item.id))
                ).scalar_one_or_none()
                if photo is not None:
                    photo.image_file_id = media_file.id
                    # Denormalized from media_files for fast reads without a
                    # join -- source of truth for the file's own pixel
                    # dimensions remains media_files.width/height.
                    photo.width = media_file.width
                    photo.height = media_file.height
            return f"linked image -> {item.kind} '{stem}'"

        return f"skipped '{source.name}' (extension doesn't match media_item kind '{item.kind}')"

    album = (await session.execute(select(Album).where(Album.slug == stem))).scalar_one_or_none()
    if album is not None and ext in IMAGE_EXTENSIONS:
        media_file = await _get_or_create_media_file(session, source, "albums")
        album.cover_media_file_id = media_file.id
        return f"linked cover -> album '{stem}'"

    return f"skipped '{source.name}' (no media_item or album with slug '{stem}')"


async def run(directory: Path) -> None:
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    async with async_session_factory() as session:
        for path in files:
            print(await _ingest_file(session, path))
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local media files into Postgres + MEDIA_ROOT")
    parser.add_argument("--dir", required=True, type=Path, help="Directory of source media files to ingest")
    args = parser.parse_args()
    asyncio.run(run(args.dir))


if __name__ == "__main__":
    main()
