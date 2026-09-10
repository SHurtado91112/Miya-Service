"""Auth unit tests that need no database.

Google is stubbed out everywhere: these cover *our* logic -- claim validation,
token minting, signature verification -- not Google's. The DB-backed sign-in and
rotation paths live in test_auth_db.py.
"""

import time
import urllib.parse
import uuid

import jwt
import pytest

from miya_server.auth import tokens
from miya_server.auth.errors import AuthError
from miya_server.config import get_settings
from miya_server.media.storage import _signed, verify_signature


def test_access_token_round_trips():
    user_id = uuid.uuid4()
    token, expires_at = tokens.mint_access_token(user_id)
    assert tokens.verify_access_token(token) == user_id
    assert expires_at.timestamp() > time.time()


def test_expired_access_token_is_rejected():
    settings = get_settings()
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) - 10},
        settings.jwt_secret,
        algorithm=tokens.ALGORITHM,
    )
    with pytest.raises(AuthError):
        tokens.verify_access_token(expired)


def test_access_token_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 3600},
        "not-our-secret",
        algorithm=tokens.ALGORITHM,
    )
    with pytest.raises(AuthError):
        tokens.verify_access_token(forged)


def test_refresh_tokens_are_stored_only_as_hashes():
    raw = "a-refresh-token"
    assert tokens._hash(raw) != raw
    assert tokens._hash(raw) == tokens._hash(raw)
    assert len(tokens._hash(raw)) == 64


def test_media_signature_accepts_what_we_minted():
    path = f"/media/{uuid.uuid4()}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(_signed(path)).query)
    assert verify_signature(path, int(query["exp"][0]), query["sig"][0])


def test_media_signature_rejects_tampering():
    path = f"/media/{uuid.uuid4()}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(_signed(path)).query)
    exp, sig = int(query["exp"][0]), query["sig"][0]

    # A different path with the same signature -- the whole point of signing.
    assert not verify_signature(f"/media/{uuid.uuid4()}", exp, sig)
    # A stretched expiry.
    assert not verify_signature(path, exp + 86400, sig)
    # A forged signature.
    assert not verify_signature(path, exp, "0" * 64)


def test_media_signature_rejects_expiry_in_the_past():
    path = f"/media/{uuid.uuid4()}"
    past = int(time.time()) - 1
    from miya_server.media.storage import _sign

    assert not verify_signature(path, past, _sign(path, past))


def test_media_urls_are_stable_so_caching_works():
    """A per-request expiry would hand back a new URL every time and defeat both
    URLCache and the immutable Cache-Control header on /media."""
    path = f"/media/{uuid.uuid4()}"
    assert _signed(path) == _signed(path)


async def test_gated_query_returns_401_not_200(client):
    """The iOS client keys its refresh-and-retry off the HTTP status, so a
    permission failure must not arrive as 200 + errors[]."""
    response = await client.post("/graphql", json={"query": "{ sections { slug } }"})
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_viewer_is_null_when_signed_out(client):
    """Ungated on purpose: it is how a client checks whether a restored token is
    still good, without having to provoke an error."""
    response = await client.post("/graphql", json={"query": "{ viewer { email } }"})
    assert response.status_code == 200
    assert response.json()["data"]["viewer"] is None


async def test_garbage_bearer_token_is_refused(client):
    response = await client.post(
        "/graphql",
        json={"query": "{ sections { slug } }"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401
