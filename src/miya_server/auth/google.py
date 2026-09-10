"""Google half of sign-in: trade the authorization code for an id_token, then
prove that id_token really came from Google and really names our app.

The exchange happens here, on the server, rather than on the device. The device
sends us the `code` and its PKCE `code_verifier`; we call Google. That keeps
Google's own access/refresh tokens off the phone entirely -- the only
credentials that ever reach the client are the ones we mint ourselves in
`tokens.py`, which we can revoke.
"""

import hmac
import logging
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

from miya_server.auth.errors import AuthError
from miya_server.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
# Google mints tokens with either form of issuer; both are legitimate.
VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

# PyJWKClient caches keys in-process and refetches on an unknown `kid`, so
# Google's routine key rotation is handled without a restart. Module-level so
# the cache is actually shared across requests.
_jwk_client = PyJWKClient(JWKS_URI, cache_keys=True)


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    avatar_url: str | None


async def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> str:
    """Swap an authorization code for Google's id_token.

    No client_secret: an iOS OAuth client is a *public* client, and Google
    documents the secret as not applicable to it. PKCE is what authenticates the
    request -- only the app that generated the verifier can redeem the code.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "code_verifier": code_verifier,
                "client_id": settings.google_ios_client_id,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        logger.warning("Google token exchange failed: %s %s", response.status_code, response.text)
        raise AuthError("Could not complete Google sign-in.")

    id_token = response.json().get("id_token")
    if not id_token:
        logger.warning("Google token exchange returned no id_token")
        raise AuthError("Could not complete Google sign-in.")
    return id_token


def verify_id_token(id_token: str, nonce: str) -> GoogleIdentity:
    """Validate the id_token's signature and claims, and pull the identity out.

    Two checks carry the weight here:

    * `aud` -- without it, an id_token Google minted for some *other* app could
      be replayed here to impersonate that app's users.
    * `nonce` -- ties this token to the single authorization request our app
      just made. The device generates it, we pass it to Google in the authorize
      URL, and Google echoes it back inside the signed token. A token captured
      from an earlier flow carries the wrong nonce and is refused.
    """
    settings = get_settings()
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_ios_client_id,
            issuer=VALID_ISSUERS,
            options={"require": ["sub", "aud", "iss", "exp", "nonce"]},
        )
    except Exception as exc:
        logger.warning("Google id_token rejected: %s", exc)
        raise AuthError("Could not complete Google sign-in.") from exc

    # compare_digest, not ==: the nonce is a secret being compared against
    # attacker-influenced input, so the comparison should not leak its prefix
    # through timing.
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        logger.warning("Google id_token nonce mismatch for sub=%s", claims.get("sub"))
        raise AuthError("Could not complete Google sign-in.")

    # An unverified address could be attacker-chosen. We key identity on `sub`,
    # so this does not gate account matching -- but we display the address and
    # would rather not show one nobody has proven they own.
    if not claims.get("email_verified", False):
        logger.warning("Google id_token for sub=%s has unverified email", claims.get("sub"))
        raise AuthError("Your Google account's email address is not verified.")

    return GoogleIdentity(
        sub=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name"),
        avatar_url=claims.get("picture"),
    )
