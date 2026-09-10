"""Sign-in, rotation, and reuse detection against a real database.

Google is stubbed at the module boundary (`exchange_code` / `verify_id_token`),
so these exercise our persistence and token lifecycle, never Google's.
"""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from miya_server.auth import google
from miya_server.auth.google import GoogleIdentity
from miya_server.db.base import async_session_factory
from miya_server.db.models import RefreshToken, User

pytestmark = pytest.mark.usefixtures("seeded_db")

_SIGN_IN = """
mutation($code: String!, $verifier: String!, $redirect: String!, $nonce: String!) {
  signInWithGoogle(code: $code, codeVerifier: $verifier,
                   redirectUri: $redirect, nonce: $nonce) {
    accessToken refreshToken user { email name }
  }
}
"""

_REFRESH = """
mutation($token: String!) {
  refreshSession(refreshToken: $token) { accessToken refreshToken user { email } }
}
"""

_SIGN_OUT = "mutation($token: String!) { signOut(refreshToken: $token) }"


class _StubGoogle:
    """Holder for the identity the stubbed Google returns. `GoogleIdentity` is
    frozen, so a test that simulates a renamed account swaps the whole value."""

    def __init__(self, identity: GoogleIdentity) -> None:
        self.identity = identity

    @property
    def sub(self) -> str:
        return self.identity.sub

    def rename(self, **changes) -> None:
        self.identity = replace(self.identity, **changes)


@pytest.fixture
def stub_google(monkeypatch):
    stub = _StubGoogle(
        GoogleIdentity(
            sub=f"google-sub-{uuid.uuid4()}",
            email="signin@example.com",
            name="Sign In",
            avatar_url="https://example.com/a.png",
        )
    )

    async def fake_exchange(code, code_verifier, redirect_uri):
        return "stub-id-token"

    def fake_verify(id_token, nonce):
        return stub.identity

    monkeypatch.setattr(google, "exchange_code", fake_exchange)
    monkeypatch.setattr(google, "verify_id_token", fake_verify)
    return stub


async def _sign_in(client):
    response = await client.post(
        "/graphql",
        json={
            "query": _SIGN_IN,
            "variables": {
                "code": "auth-code",
                "verifier": "verifier",
                "redirect": "com.example:/oauth2redirect",
                "nonce": "nonce",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body, body
    return body["data"]["signInWithGoogle"]


async def test_sign_in_creates_a_user_and_returns_a_session(client, stub_google):
    payload = await _sign_in(client)
    assert payload["user"]["email"] == "signin@example.com"
    assert payload["accessToken"] and payload["refreshToken"]

    async with async_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.google_sub == stub_google.sub))
        ).scalar_one()
        assert user.name == "Sign In"


async def test_second_sign_in_reuses_the_user_and_refreshes_the_profile(client, stub_google):
    first = await _sign_in(client)

    # Same Google account, renamed. Identity is keyed on `sub`, so this must
    # update the existing row rather than create a second user.
    stub_google.rename(name="Renamed", email="renamed@example.com")
    second = await _sign_in(client)

    assert second["user"]["name"] == "Renamed"
    assert first["refreshToken"] != second["refreshToken"]

    async with async_session_factory() as session:
        users = (
            await session.execute(select(User).where(User.google_sub == stub_google.sub))
        ).scalars().all()
        assert len(users) == 1
        assert users[0].email == "renamed@example.com"


async def test_access_token_from_sign_in_unlocks_gated_queries(client, stub_google):
    payload = await _sign_in(client)

    anonymous = await client.post("/graphql", json={"query": "{ sections { slug } }"})
    assert anonymous.status_code == 401

    authorized = await client.post(
        "/graphql",
        json={"query": "{ sections { slug } }"},
        headers={"Authorization": f"Bearer {payload['accessToken']}"},
    )
    assert authorized.status_code == 200
    assert "errors" not in authorized.json()


async def test_refresh_rotates_the_token(client, stub_google):
    payload = await _sign_in(client)
    original = payload["refreshToken"]

    response = await client.post("/graphql", json={"query": _REFRESH, "variables": {"token": original}})
    body = response.json()
    assert "errors" not in body, body
    rotated = body["data"]["refreshSession"]["refreshToken"]
    assert rotated != original

    # The successor works.
    again = await client.post("/graphql", json={"query": _REFRESH, "variables": {"token": rotated}})
    assert "errors" not in again.json()


async def test_replaying_a_spent_token_revokes_every_session(client, stub_google):
    """Reuse means the token leaked. We cannot tell the victim from the thief,
    so the whole family dies and the real user signs in again."""
    payload = await _sign_in(client)
    original = payload["refreshToken"]

    rotated = (
        await client.post("/graphql", json={"query": _REFRESH, "variables": {"token": original}})
    ).json()["data"]["refreshSession"]["refreshToken"]

    # Replay the spent one.
    replay = await client.post("/graphql", json={"query": _REFRESH, "variables": {"token": original}})
    assert "errors" in replay.json()

    # The successor is collateral damage -- that is the point.
    after = await client.post("/graphql", json={"query": _REFRESH, "variables": {"token": rotated}})
    assert "errors" in after.json()

    async with async_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.google_sub == stub_google.sub))
        ).scalar_one()
        live = (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
                )
            )
        ).scalars().all()
        assert live == []


async def test_sign_out_revokes_the_refresh_token(client, stub_google):
    payload = await _sign_in(client)

    out = await client.post(
        "/graphql", json={"query": _SIGN_OUT, "variables": {"token": payload["refreshToken"]}}
    )
    assert out.json()["data"]["signOut"] is True

    after = await client.post(
        "/graphql", json={"query": _REFRESH, "variables": {"token": payload["refreshToken"]}}
    )
    assert "errors" in after.json()


async def test_sign_out_is_idempotent(client):
    """A client whose access token already expired must still be able to sign
    out cleanly, and repeating it must not error."""
    out = await client.post("/graphql", json={"query": _SIGN_OUT, "variables": {"token": "never-issued"}})
    assert out.json()["data"]["signOut"] is True


async def test_viewer_reports_the_signed_in_user(client, stub_google):
    payload = await _sign_in(client)
    response = await client.post(
        "/graphql",
        json={"query": "{ viewer { email name } }"},
        headers={"Authorization": f"Bearer {payload['accessToken']}"},
    )
    assert response.json()["data"]["viewer"]["email"] == "signin@example.com"
