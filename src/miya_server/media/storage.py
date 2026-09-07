from uuid import UUID

from miya_server.config import get_settings


def build_media_url(file_id: UUID | None) -> str | None:
    """Resolve a media_files.id into an absolute, self-hosted /media/{id} URL.

    Never expose raw filesystem paths through the API."""
    if file_id is None:
        return None
    settings = get_settings()
    return f"{settings.public_base_url}/media/{file_id}"


def build_thumbnail_url(file_id: UUID | None) -> str | None:
    """The /media/{id}/thumb URL for the same media_files.id. Emitted whenever
    build_media_url is -- the endpoint serves the original bytes when no
    thumbnail has been generated yet, so this is never a broken link."""
    if file_id is None:
        return None
    settings = get_settings()
    return f"{settings.public_base_url}/media/{file_id}/thumb"
