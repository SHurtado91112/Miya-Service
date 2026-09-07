"""Thumbnail generation for stored media images.

A thumbnail is a small WebP derivative of an image stored under MEDIA_ROOT,
written to disk next to the original (same UUID stem, ``_thumb.webp`` suffix)
and recorded in the ``thumbnail_*`` columns of the owning ``media_files`` row.
Aspect ratio is preserved and the longest edge is clamped to
``THUMBNAIL_MAX_EDGE`` -- images already smaller than that are re-encoded at
their original size, never upscaled.

`generate_thumbnail_bytes` is a pure function (no DB, no settings). The ingest
CLI calls it inline for every new image; `backfill-thumbnails` (registered as a
console script) walks existing rows that predate this feature.

Run the backfill via: uv run backfill-thumbnails
"""

import asyncio
import io
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.config import get_settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import MediaFile

THUMBNAIL_MAX_EDGE = 512
THUMBNAIL_QUALITY = 80
THUMBNAIL_MIME = "image/webp"
THUMBNAIL_SUFFIX = "_thumb.webp"


def generate_thumbnail_bytes(
    source: Path, *, max_edge: int = THUMBNAIL_MAX_EDGE, quality: int = THUMBNAIL_QUALITY
) -> tuple[bytes, int, int]:
    """Open ``source``, honour EXIF orientation, downscale so the longest edge is
    ``<= max_edge`` (aspect preserved, never upscaled), and encode WebP.

    Returns ``(webp_bytes, width, height)``. Raises if ``source`` cannot be
    decoded by Pillow (callers treat that as "no thumbnail").
    """
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=6)
        return buf.getvalue(), img.width, img.height


def thumbnail_relative_path_for(relative_path: str) -> str:
    """``photos/<uuid>.jpg`` -> ``photos/<uuid>_thumb.webp`` (same directory and
    stem as the original, so cleanup is obvious)."""
    p = Path(relative_path)
    return str(p.with_name(p.stem + THUMBNAIL_SUFFIX))


async def _backfill(session: AsyncSession) -> tuple[int, int]:
    settings = get_settings()
    rows = (
        await session.execute(
            select(MediaFile).where(
                MediaFile.mime_type.like("image/%"),
                MediaFile.thumbnail_relative_path.is_(None),
            )
        )
    ).scalars().all()

    generated = skipped = 0
    for media_file in rows:
        source = settings.media_root / media_file.relative_path
        if not source.is_file():
            print(f"skipped {media_file.relative_path} (missing on disk)")
            skipped += 1
            continue
        try:
            data, width, height = generate_thumbnail_bytes(source)
        except Exception as exc:  # noqa: BLE001 -- best-effort, e.g. HEIC / corrupt
            print(f"skipped {media_file.relative_path} ({exc})")
            skipped += 1
            continue
        rel = thumbnail_relative_path_for(media_file.relative_path)
        dest = settings.media_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        media_file.thumbnail_relative_path = rel
        media_file.thumbnail_width = width
        media_file.thumbnail_height = height
        media_file.thumbnail_mime_type = THUMBNAIL_MIME
        print(f"generated {rel} ({width}x{height})")
        generated += 1

    return generated, skipped


async def run() -> None:
    async with async_session_factory() as session:
        generated, skipped = await _backfill(session)
        await session.commit()
    print(f"Done: {generated} thumbnails generated, {skipped} skipped.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
