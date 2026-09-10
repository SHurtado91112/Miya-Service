from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://miya:miya@localhost:5432/miya"
    media_root: Path = Path("./media")
    public_base_url: str = "http://localhost:8000"

    # --- Auth ---------------------------------------------------------------
    # The *iOS* OAuth client id from Google Cloud Console (the one whose bundle
    # id is com.hurtado.Miya). Public, not a secret: it is also compiled into
    # the app's Info.plist. Every Google id_token we accept must carry this as
    # its `aud`, which is what stops a token minted for some other app from
    # being replayed against us.
    google_ios_client_id: str = ""
    # HS256 signing key for our own access tokens. Rotating it invalidates every
    # outstanding access token (refresh tokens survive -- they are opaque).
    jwt_secret: str = ""
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    # HMAC key for signed /media URLs. Separate from jwt_secret so media links
    # can be invalidated without logging everyone out.
    media_url_secret: str = ""
    # Signed media URLs must outlive a long listening session and play well with
    # the immutable Cache-Control on /media responses.
    media_url_ttl_seconds: int = 7 * 24 * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
