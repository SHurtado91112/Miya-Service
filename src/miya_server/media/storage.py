import hashlib
import hmac
import time
from uuid import UUID

from miya_server.config import get_settings


def _sign(path: str, expires_at: int) -> str:
    settings = get_settings()
    message = f"{path}:{expires_at}".encode()
    return hmac.new(settings.media_url_secret.encode(), message, hashlib.sha256).hexdigest()


def verify_signature(path: str, expires_at: int, signature: str) -> bool:
    """Constant-time check that we minted this link and it has not expired.

    `compare_digest` rather than `==`: a byte-at-a-time comparison leaks, via
    timing, how much of a guessed signature was correct, which is enough to
    forge one a byte at a time.
    """
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(_sign(path, expires_at), signature)


# Expiries snap to this grid so a URL stays byte-identical across requests.
_EXPIRY_BUCKET_SECONDS = 3600


def _signed(path: str) -> str:
    """Attach an expiring HMAC to a /media path.

    Bearer tokens are not an option here: these URLs are handed to AVPlayer and
    AsyncImage, which fetch them directly and attach no headers of ours. Signing
    the URL itself is what keeps the library from being readable by anyone who
    can reach the host.

    The expiry is rounded up to a bucket rather than computed from `now`. A
    per-request expiry would make every GraphQL response hand back a
    *different* URL for the same unchanged bytes, and both `URLCache` and
    `AsyncImage` key on the full URL -- so the `max-age=31536000, immutable`
    header on /media responses would never once be honoured. Bucketing keeps
    the URL stable for an hour at a time, which is what makes the cache work.
    """
    settings = get_settings()
    now = int(time.time())
    horizon = now + settings.media_url_ttl_seconds
    expires_at = -(-horizon // _EXPIRY_BUCKET_SECONDS) * _EXPIRY_BUCKET_SECONDS
    signature = _sign(path, expires_at)
    return f"{settings.public_base_url}{path}?exp={expires_at}&sig={signature}"


def build_media_url(file_id: UUID | None) -> str | None:
    """Resolve a media_files.id into an absolute, self-hosted /media/{id} URL.

    Never expose raw filesystem paths through the API."""
    if file_id is None:
        return None
    return _signed(f"/media/{file_id}")


def build_thumbnail_url(file_id: UUID | None) -> str | None:
    """The /media/{id}/thumb URL for the same media_files.id. Emitted whenever
    build_media_url is -- the endpoint serves the original bytes when no
    thumbnail has been generated yet, so this is never a broken link."""
    if file_id is None:
        return None
    return _signed(f"/media/{file_id}/thumb")
