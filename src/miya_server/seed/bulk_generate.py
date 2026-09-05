"""Generates a large synthetic corpus of albums/songs/photos for scale testing
(pagination, fuzzy search over pg_trgm, on-device rendering of large libraries).

Unlike `seed_data.py` (curated, hand-written fixtures for demos), this creates
procedurally-named rows directly via SQLAlchemy and writes matching placeholder
media source files (tiny PNGs for photos/covers, tiny silent WAVs for songs) to
a scratch directory. Only a bounded sample of the generated rows is linked into
the Home sections, so the UI stays usable -- the full corpus remains queryable
via `albums`/`searchMedia`.

After running this, ingest the generated media files with the existing CLI:
    uv run ingest-media --dir var/bulk-media-source

Run via: uv run generate-bulk-data [--song-albums N] [--photo-albums N] [--media-dir PATH]

To undo the Home-section wiring (remove the legacy erroneous "bulk-music" /
"bulk-photos" sections and their link rows) without touching the generated
corpus:
    uv run generate-bulk-data --clean

To (re)link a bounded, deterministic sample of an already-generated bulk corpus
into the curated "music" / "photos" sections without regenerating anything:
    uv run generate-bulk-data --relink-sections
"""

import argparse
import asyncio
import io
import random
import wave
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from miya_server.db.base import async_session_factory
from miya_server.db.models import Album, MediaItem, Photo, Section, Song
from miya_server.db.models.associations import section_albums, section_items

# Home sections the bulk sample links into. These are the curated sections
# created by the base seed (`uv run seed`); the bulk generator must never create
# its own "bulk-*" sections.
#   slug -> (fallback title, fallback sort_order)
TARGET_SECTIONS = {
    "song": ("music", "Music", 0),
    "photo": ("photos", "Photos", 1),
}

# Slugs of the erroneous extra sections earlier versions of this script created.
# Used only by --clean.
LEGACY_BULK_SECTION_SLUGS = ("bulk-music", "bulk-photos")

ADJECTIVES = [
    "Crimson", "Electric", "Silent", "Golden", "Hollow", "Neon", "Velvet", "Broken",
    "Distant", "Midnight", "Amber", "Frozen", "Wild", "Quiet", "Restless", "Faded",
    "Iron", "Paper", "Glass", "Copper",
]
NOUNS_SONG = [
    "Wolf", "Bloom", "Signal", "Harbor", "Static", "Horizon", "Ember", "Echo",
    "Current", "Orbit", "Compass", "Wire", "Canyon", "Tide", "Ash", "Fable",
    "Lantern", "Vessel", "Drift", "Halo",
]
NOUNS_PHOTO = [
    "Trail", "Market", "Skyline", "Garden", "Alley", "Pier", "Meadow", "Rooftop",
    "Station", "Overlook", "Courtyard", "Harbor", "Ridge", "Plaza", "Terrace",
    "Boardwalk", "Quarry", "Orchard", "Wharf", "Summit",
]
ARTISTS = [
    "Bey-Zed",
    "Tay-Tay Swiftly",
    "Ed Shealing",
    "Bruno Mercury",
    "Kanye East",
    "Ari-Grandeur",
    "The Weekday",
    "Justin Timberflake",
    "Adelle-evated",
    "Post Malorne",
    "Dua Liptho",
    "Billie Irish",
    "Drakeless",
    "Lady Ga-Ga-Gone",
    "Harry Sytles",
    "Rihanna-Not",
    "Elton Johnny",
    "Freddie Mercuriy",
    "Kurt Cobainless",
    "Jon Bongiovi Jr.",
]


def _slug(prefix: str, index: int) -> str:
    return f"{prefix}-{index:05d}"


def _make_cover_png(rng: random.Random) -> bytes:
    color = (rng.randrange(40, 220), rng.randrange(40, 220), rng.randrange(40, 220))
    img = Image.new("RGB", (256, 256), color=color)
    draw = ImageDraw.Draw(img)
    accent = tuple(min(255, c + 60) for c in color)
    draw.rectangle([32, 32, 224, 224], outline=accent, width=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_silent_wav(seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


async def _generate(
    *,
    song_albums: int,
    songs_per_album: int,
    photo_albums: int,
    photos_per_album: int,
    standalone_songs: int,
    standalone_photos: int,
    section_item_sample: int,
    section_album_sample: int,
    media_dir: Path,
    seed: int,
) -> None:
    rng = random.Random(seed)
    media_dir.mkdir(parents=True, exist_ok=True)

    all_song_slugs: list[str] = []
    all_photo_slugs: list[str] = []
    all_song_album_slugs: list[str] = []
    all_photo_album_slugs: list[str] = []

    async with async_session_factory() as session:
        # Song albums + songs
        for a in range(song_albums):
            album_slug = _slug("bulk-song-album", a)
            title = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_SONG)}"
            album = Album(slug=album_slug, title=title, subtitle=rng.choice(ARTISTS), system_image="square.stack")
            session.add(album)
            await session.flush()
            (media_dir / f"{album_slug}.png").write_bytes(_make_cover_png(rng))
            all_song_album_slugs.append(album_slug)

            for t in range(songs_per_album):
                song_slug = _slug(f"bulk-song-{a:04d}", t)
                song_title = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_SONG)}"
                item = MediaItem(
                    slug=song_slug,
                    kind="song",
                    title=song_title,
                    subtitle=album.subtitle,
                    system_image="music.note",
                    detail=f"Track {t + 1} of a generated test album.",
                    album_id=album.id,
                )
                session.add(item)
                await session.flush()
                session.add(Song(media_item_id=item.id, artist=album.subtitle, track_number=t + 1))
                (media_dir / f"{song_slug}.wav").write_bytes(_make_silent_wav())
                all_song_slugs.append(song_slug)

        # Photo albums + photos
        for a in range(photo_albums):
            album_slug = _slug("bulk-photo-album", a)
            title = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_PHOTO)}"
            album = Album(slug=album_slug, title=title, subtitle="Test Library", system_image="square.stack")
            session.add(album)
            await session.flush()
            (media_dir / f"{album_slug}.png").write_bytes(_make_cover_png(rng))
            all_photo_album_slugs.append(album_slug)

            for p in range(photos_per_album):
                photo_slug = _slug(f"bulk-photo-{a:04d}", p)
                photo_title = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_PHOTO)}"
                item = MediaItem(
                    slug=photo_slug,
                    kind="photo",
                    title=photo_title,
                    subtitle="Test Library",
                    system_image="photo",
                    detail="Generated test photo.",
                    album_id=album.id,
                )
                session.add(item)
                await session.flush()
                session.add(Photo(media_item_id=item.id))
                (media_dir / f"{photo_slug}.png").write_bytes(_make_cover_png(rng))
                all_photo_slugs.append(photo_slug)

        # Standalone items (no album)
        for i in range(standalone_songs):
            song_slug = _slug("bulk-song-standalone", i)
            item = MediaItem(
                slug=song_slug,
                kind="song",
                title=f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_SONG)}",
                subtitle=rng.choice(ARTISTS),
                system_image="music.note",
                detail="Generated standalone test song.",
            )
            session.add(item)
            await session.flush()
            session.add(Song(media_item_id=item.id, artist=item.subtitle))
            (media_dir / f"{song_slug}.wav").write_bytes(_make_silent_wav())
            all_song_slugs.append(song_slug)

        for i in range(standalone_photos):
            photo_slug = _slug("bulk-photo-standalone", i)
            item = MediaItem(
                slug=photo_slug,
                kind="photo",
                title=f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS_PHOTO)}",
                subtitle="Test Library",
                system_image="photo",
                detail="Generated standalone test photo.",
            )
            session.add(item)
            await session.flush()
            session.add(Photo(media_item_id=item.id))
            (media_dir / f"{photo_slug}.png").write_bytes(_make_cover_png(rng))
            all_photo_slugs.append(photo_slug)

        await session.commit()
        print(
            f"Created {len(all_song_slugs)} songs across {len(all_song_album_slugs)} albums, "
            f"{len(all_photo_slugs)} photos across {len(all_photo_album_slugs)} albums."
        )

        # Link a bounded, deterministic sample of the corpus into the curated
        # "music" / "photos" Home sections (songs -> music, photos -> photos).
        # Shared with the `--relink-sections` entrypoint below.
        await _link_bulk_sample_into_sections(
            session,
            section_item_sample=section_item_sample,
            section_album_sample=section_album_sample,
            seed=seed,
        )
        await session.commit()
        print("Linked sample into existing Home sections 'music' and 'photos'.")
        print(f"Wrote placeholder media source files to {media_dir}/")
        print(f"Next: uv run ingest-media --dir {media_dir}")


# Album-slug prefixes the bulk generator uses, per media kind.
_BULK_ALBUM_SLUG_PREFIX = {"song": "bulk-song-album-", "photo": "bulk-photo-album-"}


async def _link_bulk_sample_into_sections(
    session: AsyncSession,
    *,
    section_item_sample: int,
    section_album_sample: int,
    seed: int,
) -> dict[str, dict[str, int]]:
    """Sample a bounded, deterministic slice of the existing ``bulk-*`` corpus
    already in the DB and link it into the curated "music" / "photos" Home
    sections (songs -> "music", photos -> "photos").

    Never creates or regenerates albums / media_items -- it only reads
    ``bulk-``-prefixed rows and inserts ``section_items`` / ``section_albums``.
    The "music" / "photos" sections are looked up by slug; if the base seed has
    not been run they are created with plain slugs/titles (never ``bulk-*``).
    Bulk rows are appended after the current ``MAX(sort_order)`` for the section
    so they sort after the base-seed links, and every insert is
    ``ON CONFLICT DO NOTHING`` -- so re-running with the same ``seed`` is a
    no-op. Does not commit; the caller owns the transaction.

    Returns ``{section_slug: {"items_added": n, "albums_added": n}}``.
    """
    rng = random.Random(seed)
    summary: dict[str, dict[str, int]] = {}

    for kind in ("song", "photo"):
        section_slug, fallback_title, fallback_sort = TARGET_SECTIONS[kind]
        section_row = (
            await session.execute(select(Section).where(Section.slug == section_slug))
        ).scalar_one_or_none()
        if section_row is None:
            section_row = Section(
                slug=section_slug, title=fallback_title, sort_order=fallback_sort
            )
            session.add(section_row)
            await session.flush()
        section_id = section_row.id

        # Stable ordering (by slug) before sampling so the same seed always
        # yields the same picks regardless of DB row order.
        item_rows = (
            await session.execute(
                select(MediaItem.id, MediaItem.slug)
                .where(MediaItem.kind == kind, MediaItem.slug.like("bulk-%"))
                .order_by(MediaItem.slug)
            )
        ).all()
        album_rows = (
            await session.execute(
                select(Album.id, Album.slug)
                .where(Album.slug.like(f"{_BULK_ALBUM_SLUG_PREFIX[kind]}%"))
                .order_by(Album.slug)
            )
        ).all()

        sampled_items = rng.sample(item_rows, min(section_item_sample, len(item_rows)))
        sampled_albums = rng.sample(album_rows, min(section_album_sample, len(album_rows)))

        # The base seed populates these sections with low sort_order values --
        # append after the current max so bulk samples sort after them.
        item_base = (
            await session.execute(
                select(func.coalesce(func.max(section_items.c.sort_order), -1) + 1).where(
                    section_items.c.section_id == section_id
                )
            )
        ).scalar_one()
        album_base = (
            await session.execute(
                select(func.coalesce(func.max(section_albums.c.sort_order), -1) + 1).where(
                    section_albums.c.section_id == section_id
                )
            )
        ).scalar_one()

        items_added = 0
        for offset, row in enumerate(sampled_items):
            result = await session.execute(
                pg_insert(section_items)
                .values(
                    section_id=section_id,
                    media_item_id=row.id,
                    sort_order=item_base + offset,
                )
                .on_conflict_do_nothing()
            )
            items_added += result.rowcount

        albums_added = 0
        for offset, row in enumerate(sampled_albums):
            result = await session.execute(
                pg_insert(section_albums)
                .values(
                    section_id=section_id,
                    album_id=row.id,
                    sort_order=album_base + offset,
                )
                .on_conflict_do_nothing()
            )
            albums_added += result.rowcount

        summary[section_slug] = {"items_added": items_added, "albums_added": albums_added}

    return summary


async def _relink_sections(
    *,
    section_item_sample: int,
    section_album_sample: int,
    seed: int,
) -> None:
    """Standalone, idempotent entrypoint (``--relink-sections``): link a bounded
    deterministic sample of the existing ``bulk-*`` corpus into the "music" /
    "photos" Home sections. Regenerates nothing.
    """
    async with async_session_factory() as session:
        summary = await _link_bulk_sample_into_sections(
            session,
            section_item_sample=section_item_sample,
            section_album_sample=section_album_sample,
            seed=seed,
        )
        await session.commit()

    for section_slug, counts in summary.items():
        print(
            f"{section_slug}: +{counts['items_added']} section_items, "
            f"+{counts['albums_added']} section_albums"
        )
    if all(c["items_added"] == 0 and c["albums_added"] == 0 for c in summary.values()):
        print("(no new rows -- sections already hold this sample)")
    print("Relink complete.")


async def _clean() -> None:
    """Idempotently remove the erroneous extra Home sections that earlier
    versions of this script created (slugs in LEGACY_BULK_SECTION_SLUGS) and
    their section_items / section_albums rows.

    Deliberately does NOT touch the base seed sections ("music", "photos"), the
    base seed albums, or any generated bulk-* albums / media_items -- the large
    synthetic corpus stays in place for pagination / search scale testing.
    """
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                Section.__table__.select().where(Section.slug.in_(LEGACY_BULK_SECTION_SLUGS))
            )
        ).fetchall()
        if not rows:
            print(
                "Nothing to clean: no "
                f"{' / '.join(LEGACY_BULK_SECTION_SLUGS)} sections present."
            )
            remaining = (await session.execute(Section.__table__.select())).fetchall()
            print("Sections: " + ", ".join(sorted(r.slug for r in remaining)))
            return

        section_ids = [r.id for r in rows]
        n_items = (
            await session.execute(
                select(func.count())
                .select_from(section_items)
                .where(section_items.c.section_id.in_(section_ids))
            )
        ).scalar_one()
        n_albums = (
            await session.execute(
                select(func.count())
                .select_from(section_albums)
                .where(section_albums.c.section_id.in_(section_ids))
            )
        ).scalar_one()

        print("Removing erroneous bulk sections:")
        for r in rows:
            print(f"  - {r.slug}  (id={r.id}, sort_order={r.sort_order})")
        print(f"  section_items rows to delete:  {n_items}")
        print(f"  section_albums rows to delete: {n_albums}")

        await session.execute(
            section_items.delete().where(section_items.c.section_id.in_(section_ids))
        )
        await session.execute(
            section_albums.delete().where(section_albums.c.section_id.in_(section_ids))
        )
        await session.execute(Section.__table__.delete().where(Section.id.in_(section_ids)))
        await session.commit()

        remaining = (await session.execute(Section.__table__.select())).fetchall()
        print(
            f"Deleted {len(rows)} sections, {n_items} section_items, {n_albums} section_albums."
        )
        print("Remaining sections: " + ", ".join(sorted(r.slug for r in remaining)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a large synthetic media corpus for scale testing")
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Remove the erroneous extra Home sections ('bulk-music' / 'bulk-photos') "
            "and their link rows, then exit. Idempotent. Leaves bulk albums / "
            "media_items untouched."
        ),
    )
    parser.add_argument(
        "--relink-sections",
        action="store_true",
        help=(
            "Link a bounded, deterministic sample of the EXISTING bulk-* corpus "
            "into the 'music' / 'photos' sections (songs -> music, photos -> "
            "photos), then exit. Regenerates nothing. Idempotent for a given "
            "--seed / --section-*-sample. Uses --section-item-sample, "
            "--section-album-sample, --seed."
        ),
    )
    parser.add_argument("--song-albums", type=int, default=250)
    parser.add_argument("--songs-per-album", type=int, default=10)
    parser.add_argument("--photo-albums", type=int, default=250)
    parser.add_argument("--photos-per-album", type=int, default=10)
    parser.add_argument("--standalone-songs", type=int, default=50)
    parser.add_argument("--standalone-photos", type=int, default=50)
    parser.add_argument("--section-item-sample", type=int, default=100)
    parser.add_argument("--section-album-sample", type=int, default=40)
    parser.add_argument("--media-dir", type=Path, default=Path("var/bulk-media-source"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.clean:
        asyncio.run(_clean())
        return

    if args.relink_sections:
        asyncio.run(
            _relink_sections(
                section_item_sample=args.section_item_sample,
                section_album_sample=args.section_album_sample,
                seed=args.seed,
            )
        )
        return

    asyncio.run(
        _generate(
            song_albums=args.song_albums,
            songs_per_album=args.songs_per_album,
            photo_albums=args.photo_albums,
            photos_per_album=args.photos_per_album,
            standalone_songs=args.standalone_songs,
            standalone_photos=args.standalone_photos,
            section_item_sample=args.section_item_sample,
            section_album_sample=args.section_album_sample,
            media_dir=args.media_dir,
            seed=args.seed,
        )
    )


if __name__ == "__main__":
    main()
