"""Local ingest CLI: matches files under a directory to existing media_items
(by slug == filename stem), albums (for cover art), or authors (portraits, via
an ``author-<slug>`` filename prefix), copies them into MEDIA_ROOT, creates
media_files rows, and backfills the FKs (media_items.primary_media_file_id,
songs.audio_file_id, photos.image_file_id, albums.cover_media_file_id,
authors.profile_media_file_id).

Every ingested image also gets a generated WebP thumbnail written next to it and
recorded in media_files.thumbnail_* (best-effort -- an undecodable source just
leaves those columns NULL).

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
from miya_server.db.models import Album, Author, MediaFile, MediaItem, Photo, Song
from miya_server.media.thumbnails import (
    THUMBNAIL_MIME,
    generate_thumbnail_bytes,
    thumbnail_relative_path_for,
)

_AUTHOR_PREFIX = "author-"

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
    thumb_relative = thumb_width = thumb_height = thumb_mime = None
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        width, height = _image_dimensions(dest_path)
        thumb_relative, thumb_width, thumb_height, thumb_mime = _generate_thumbnail(
            settings, dest_path, dest_relative
        )

    media_file = MediaFile(
        id=file_id,
        relative_path=dest_relative,
        mime_type=mime_type,
        size_bytes=dest_path.stat().st_size,
        width=width,
        height=height,
        checksum_sha256=checksum,
        thumbnail_relative_path=thumb_relative,
        thumbnail_width=thumb_width,
        thumbnail_height=thumb_height,
        thumbnail_mime_type=thumb_mime,
    )
    session.add(media_file)
    await session.flush()
    return media_file


def _generate_thumbnail(
    settings, source: Path, relative_path: str
) -> tuple[str | None, int | None, int | None, str | None]:
    """Write a WebP thumbnail next to the just-copied original. Best-effort:
    an undecodable source (e.g. HEIC without a plugin) yields all-None, matching
    _image_dimensions -- ingest never fails over a derivative."""
    try:
        data, width, height = generate_thumbnail_bytes(source)
    except Exception:  # noqa: BLE001 -- best-effort metadata, never fail ingest over it
        return None, None, None, None
    thumb_relative = thumbnail_relative_path_for(relative_path)
    thumb_path = settings.media_root / thumb_relative
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(data)
    return thumb_relative, width, height, THUMBNAIL_MIME


async def _ingest_file(session: AsyncSession, source: Path) -> str:
    stem = source.stem
    ext = source.suffix.lower()

    # Author portraits: `author-<slug>.<ext>`. Checked before the media_item /
    # album lookups so an author slug that collides with an item/album slug
    # can't misattach the portrait.
    if ext in IMAGE_EXTENSIONS and stem.startswith(_AUTHOR_PREFIX):
        author_slug = stem[len(_AUTHOR_PREFIX):]
        author = (
            await session.execute(select(Author).where(Author.slug == author_slug))
        ).scalar_one_or_none()
        if author is None:
            return f"skipped '{source.name}' (no author with slug '{author_slug}')"
        media_file = await _get_or_create_media_file(session, source, "authors")
        author.profile_media_file_id = media_file.id
        return f"linked portrait -> author '{author_slug}'"

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
