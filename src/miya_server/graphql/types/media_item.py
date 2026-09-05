from datetime import datetime
from uuid import UUID

import strawberry
from strawberry import relay

from miya_server.db.models import MediaItem as DBMediaItem
from miya_server.db.models import Photo as DBPhoto
from miya_server.db.models import Song as DBSong
from miya_server.media.storage import build_media_url
from miya_server.repositories import media_items as media_items_repo


@strawberry.interface
class MediaItem(relay.Node):
    id: relay.NodeID[UUID]
    slug: str
    title: str
    subtitle: str
    system_image: str
    detail: str
    image_url: str | None

    @classmethod
    async def resolve_nodes(
        cls,
        *,
        info: strawberry.Info,
        node_ids: list[str],
        required: bool = False,
    ) -> list["Song | Photo | None"]:
        session = info.context.session
        db_items = await media_items_repo.batch_get_media_items(
            session, [UUID(nid) for nid in node_ids]
        )
        entry_map = await build_media_entry_map(
            session, [item for item in db_items if item is not None]
        )
        out: list[Song | Photo | None] = []
        for nid, item in zip(node_ids, db_items, strict=True):
            node = entry_map.get(item.id) if item is not None else None
            if node is None and required:
                raise ValueError(f"MediaItem with id {nid!r} not found")
            out.append(node)
        return out


@strawberry.type
class AlbumRef:
    """Lightweight album reference, used for a song/photo's back-link to its
    album -- distinct from the full Album type, which also resolves items."""

    id: strawberry.ID
    slug: str
    title: str
    subtitle: str
    system_image: str
    image_url: str | None


@strawberry.type
class Song(MediaItem):
    artist: str
    audio_url: str | None
    duration_seconds: int | None
    track_number: int | None
    _album_id: strawberry.Private[UUID | None]

    @strawberry.field
    async def album(self, info: strawberry.Info) -> AlbumRef | None:
        if self._album_id is None:
            return None
        db_album = await info.context.album_loader.load(self._album_id)
        return _to_album_ref(db_album) if db_album else None


@strawberry.type
class Photo(MediaItem):
    capture_date: datetime | None
    width: int | None
    height: int | None
    camera_make: str | None
    camera_model: str | None
    iso: int | None
    aperture: float | None
    shutter_speed: str | None
    focal_length_mm: float | None
    _album_id: strawberry.Private[UUID | None]

    @strawberry.field
    async def album(self, info: strawberry.Info) -> AlbumRef | None:
        if self._album_id is None:
            return None
        db_album = await info.context.album_loader.load(self._album_id)
        return _to_album_ref(db_album) if db_album else None


def _to_album_ref(db_album) -> AlbumRef:
    return AlbumRef(
        id=strawberry.ID(str(db_album.id)),
        slug=db_album.slug,
        title=db_album.title,
        subtitle=db_album.subtitle,
        system_image=db_album.system_image,
        image_url=build_media_url(db_album.cover_media_file_id),
    )


def build_song(item: DBMediaItem, song: DBSong) -> Song:
    return Song(
        id=item.id,
        slug=item.slug,
        title=item.title,
        subtitle=item.subtitle,
        system_image=item.system_image,
        detail=item.detail,
        image_url=build_media_url(item.primary_media_file_id),
        artist=song.artist,
        audio_url=build_media_url(song.audio_file_id),
        duration_seconds=song.duration_seconds,
        track_number=song.track_number,
        _album_id=item.album_id,
    )


def build_photo(item: DBMediaItem, photo: DBPhoto) -> Photo:
    return Photo(
        id=item.id,
        slug=item.slug,
        title=item.title,
        subtitle=item.subtitle,
        system_image=item.system_image,
        detail=item.detail,
        image_url=build_media_url(photo.image_file_id or item.primary_media_file_id),
        capture_date=photo.capture_date,
        width=photo.width,
        height=photo.height,
        camera_make=photo.camera_make,
        camera_model=photo.camera_model,
        iso=photo.iso,
        aperture=float(photo.aperture) if photo.aperture is not None else None,
        shutter_speed=photo.shutter_speed,
        focal_length_mm=float(photo.focal_length_mm) if photo.focal_length_mm is not None else None,
        _album_id=item.album_id,
    )


async def build_media_entry_map(session, items: list[DBMediaItem]) -> dict[UUID, "Song | Photo"]:
    """Batch-builds Song/Photo GraphQL objects for a list of media items with
    exactly two queries total (one for songs, one for photos), regardless of
    how many items are passed -- the N+1-avoidance seam for section/album
    item lists."""
    song_ids = [item.id for item in items if item.kind == "song"]
    photo_ids = [item.id for item in items if item.kind == "photo"]
    songs_map = await media_items_repo.get_songs_map(session, song_ids)
    photos_map = await media_items_repo.get_photos_map(session, photo_ids)

    result: dict[UUID, Song | Photo] = {}
    for item in items:
        if item.kind == "song":
            song = songs_map.get(item.id)
            if song is not None:
                result[item.id] = build_song(item, song)
        elif item.kind == "photo":
            photo = photos_map.get(item.id)
            if photo is not None:
                result[item.id] = build_photo(item, photo)
    return result


async def build_media_entries(session, items: list[DBMediaItem]) -> list["Song | Photo"]:
    entry_map = await build_media_entry_map(session, items)
    return [entry_map[item.id] for item in items if item.id in entry_map]


@strawberry.type
class MediaItemConnection(relay.Connection[MediaItem]):
    album_id: strawberry.Private[UUID]

    @strawberry.field
    async def total_count(self, info: strawberry.Info) -> int:
        return await media_items_repo.count_media_items_for_album(
            info.context.session, self.album_id
        )
