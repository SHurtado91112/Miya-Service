"""Sign-in, refresh, sign-out.

These are the only fields reachable without a session -- see `IsAuthenticated`,
which guards everything on `Query`.
"""

import asyncio
from datetime import datetime

import strawberry

from miya_server.auth import google, tokens
from miya_server.graphql.types.user import User, build_user
from miya_server.repositories import users as users_repo


@strawberry.type
class AuthPayload:
    access_token: str
    refresh_token: str
    expires_at: datetime
    user: User


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def sign_in_with_google(
        self,
        info: strawberry.Info,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: str,
    ) -> AuthPayload:
        """Complete the PKCE flow the app started and open a Miya session.

        The app never sees Google's tokens: it hands us the authorization code
        and the verifier that proves it owns the request, and gets back only
        credentials we issued and can revoke.
        """
        session = info.context.session

        id_token = await google.exchange_code(code, code_verifier, redirect_uri)
        # verify_id_token is sync and may fetch Google's JWKS on a cache miss.
        # Off the event loop so one cold verification can't stall every other
        # in-flight request.
        identity = await asyncio.to_thread(google.verify_id_token, id_token, nonce)

        user = await users_repo.upsert_from_google(session, identity)
        access_token, expires_at = tokens.mint_access_token(user.id)
        refresh_token = await tokens.issue_refresh_token(session, user.id)
        await session.commit()

        return AuthPayload(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            user=build_user(user),
        )

    @strawberry.mutation
    async def refresh_session(self, info: strawberry.Info, refresh_token: str) -> AuthPayload:
        """Trade a refresh token for a new pair. The old token is burned, so a
        client must store the returned one -- replaying the old is treated as
        theft and drops every session for that user."""
        session = info.context.session
        user, new_refresh_token = await tokens.redeem_refresh_token(session, refresh_token)
        access_token, expires_at = tokens.mint_access_token(user.id)
        await session.commit()

        return AuthPayload(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_at=expires_at,
            user=build_user(user),
        )

    @strawberry.mutation
    async def sign_out(self, info: strawberry.Info, refresh_token: str) -> bool:
        """Revoke one refresh token. Unauthenticated on purpose: holding the
        token is the proof, and a client whose access token has already expired
        must still be able to sign out cleanly."""
        session = info.context.session
        result = await tokens.revoke_refresh_token(session, refresh_token)
        await session.commit()
        return result
