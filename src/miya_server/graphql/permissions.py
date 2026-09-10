from typing import Any

import strawberry
from strawberry.permission import BasePermission


class IsAuthenticated(BasePermission):
    """Gate for every field that reads the library.

    Applied per-field rather than as middleware so the auth mutations
    themselves stay reachable while signed out -- you cannot require a session
    to create a session.

    Deliberately synchronous. Strawberry builds a sync extension chain for any
    field whose resolver is sync (`relay.node()`'s is), and an async
    `has_permission` returning a coroutine into that chain is never awaited --
    it reads as truthy, so the gate silently opens. Resolving the viewer eagerly
    in `get_context` is what lets this stay sync.

    It also sets the *HTTP* status to 401. Strawberry's default is to report a
    permission failure as 200 + `errors[]`, which the iOS client cannot
    distinguish from an ordinary query error -- so it would never fire its
    refresh-and-retry path and would just show a broken screen instead of
    silently renewing an expired token.
    """

    message = "Not signed in."

    def has_permission(self, source: Any, info: strawberry.Info, **kwargs: Any) -> bool:
        if info.context.viewer is not None:
            return True
        response = getattr(info.context, "response", None)
        if response is not None:
            response.status_code = 401
            response.headers["WWW-Authenticate"] = "Bearer"
        return False
