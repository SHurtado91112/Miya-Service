"""Shared helpers for Relay forward cursor pagination over keyset queries.

Cursors are opaque base64 of ``["<sort value>", "<uuid>"]`` -- the same
``(sort_key, id)`` tuple the repository layer uses for its ``WHERE (col, id) >
(:v, :id)`` keyset. Only forward pagination (``first``/``after``) is supported;
``last``/``before`` are rejected at the resolver.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from graphql import GraphQLError
from strawberry import relay

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def clamp_first(first: int | None) -> int:
    """Resolve the requested page size to a concrete limit within bounds."""
    if first is None:
        return DEFAULT_PAGE_SIZE
    if first < 0:
        raise GraphQLError("`first` must be a non-negative integer.")
    return min(first, MAX_PAGE_SIZE)


def reject_backward(last: int | None, before: str | None) -> None:
    if last is not None or before is not None:
        raise GraphQLError(
            "Backward pagination (`last`/`before`) is not supported; use `first`/`after`."
        )


def encode_cursor(prefix: str, sort_value: str, node_id: UUID) -> str:
    return relay.to_base64(prefix, json.dumps([sort_value, str(node_id)]))


def decode_cursor(prefix: str, cursor: str) -> tuple[str, UUID]:
    try:
        got_prefix, payload = relay.from_base64(cursor)
        if got_prefix != prefix:
            raise ValueError("cursor prefix mismatch")
        sort_value, id_str = json.loads(payload)
        return sort_value, UUID(id_str)
    except Exception as exc:
        raise GraphQLError(f"Invalid 'after' cursor: {cursor!r}") from exc


def build_connection[ConnectionT: relay.Connection[Any]](
    connection_cls: type[ConnectionT],
    page_rows: Sequence[Any],
    *,
    prefix: str,
    after: str | None,
    has_next_page: bool,
    key: Callable[[Any], tuple[str, UUID]],
    node: Callable[[Any], Any],
    **connection_kwargs: Any,
) -> ConnectionT:
    """Assemble a Relay connection from an already-truncated keyset page.
    ``key(row)`` yields the ``(sort_value, id)`` cursor tuple; ``node(row)``
    yields the GraphQL node object. The caller computes ``has_next_page`` from
    the ``limit + 1`` probe fetch before truncating to ``page_rows``.
    """
    edges = [
        relay.Edge(cursor=encode_cursor(prefix, *key(row)), node=node(row))
        for row in page_rows
    ]
    page_info = relay.PageInfo(
        has_next_page=has_next_page,
        has_previous_page=after is not None,
        start_cursor=edges[0].cursor if edges else None,
        end_cursor=edges[-1].cursor if edges else None,
    )
    return connection_cls(edges=edges, page_info=page_info, **connection_kwargs)
