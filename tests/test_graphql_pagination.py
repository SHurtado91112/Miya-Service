"""End-to-end Relay cursor-pagination tests for `albums` and `Album.items`.

The "no gaps / no duplicates" checks are most meaningful after
`uv run generate-bulk-data` (which produces many albums with duplicated
titles, exercising the `(title, id)` keyset tiebreaker), but they also hold
on the plain seed.
"""

import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def _gql(client, query, **variables):
    response = await client.post(
        "/graphql", json={"query": query, "variables": variables or {}}
    )
    return response.json()


ALBUMS_PAGE = """
query ($first: Int, $after: String) {
  albums(first: $first, after: $after) {
    totalCount
    pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    edges { cursor node { id slug title } }
  }
}
"""


async def _walk_all_albums(client, page_size):
    """Page through every album, returning (ordered slugs, ordered titles, totalCount)."""
    slugs: list[str] = []
    titles: list[str] = []
    after = None
    total = None
    while True:
        body = await _gql(client, ALBUMS_PAGE, first=page_size, after=after)
        assert "errors" not in body, body
        conn = body["data"]["albums"]
        total = conn["totalCount"]
        edges = conn["edges"]
        assert len(edges) <= page_size
        slugs.extend(e["node"]["slug"] for e in edges)
        titles.extend(e["node"]["title"] for e in edges)
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
        assert after is not None
    return slugs, titles, total


async def test_first_is_respected_and_has_next_page(client):
    body = await _gql(client, ALBUMS_PAGE, first=2)
    assert "errors" not in body, body
    conn = body["data"]["albums"]
    assert len(conn["edges"]) == 2
    assert conn["pageInfo"]["hasNextPage"] is True
    assert conn["pageInfo"]["hasPreviousPage"] is False
    assert conn["pageInfo"]["startCursor"] == conn["edges"][0]["cursor"]
    assert conn["pageInfo"]["endCursor"] == conn["edges"][1]["cursor"]
    assert all(e["cursor"] for e in conn["edges"])


async def test_after_cursor_advances_without_overlap(client):
    page1 = (await _gql(client, ALBUMS_PAGE, first=3))["data"]["albums"]
    page2 = (
        await _gql(client, ALBUMS_PAGE, first=3, after=page1["pageInfo"]["endCursor"])
    )["data"]["albums"]

    s1 = [e["node"]["slug"] for e in page1["edges"]]
    s2 = [e["node"]["slug"] for e in page2["edges"]]
    assert set(s1).isdisjoint(s2)
    assert page2["pageInfo"]["hasPreviousPage"] is True
    # ordering is stable across the page boundary
    assert page1["edges"][-1]["node"]["title"] <= page2["edges"][0]["node"]["title"]


async def test_full_walk_has_no_gaps_or_duplicates(client):
    slugs, titles, total = await _walk_all_albums(client, page_size=7)
    assert len(slugs) == total
    assert len(set(slugs)) == total
    assert titles == sorted(titles)


async def test_total_count_matches_full_walk(client):
    slugs, _titles, total = await _walk_all_albums(client, page_size=50)
    assert len(slugs) == total
    single = await _gql(client, ALBUMS_PAGE, first=1)
    assert single["data"]["albums"]["totalCount"] == total


async def test_last_page_then_empty_tail(client):
    # walk to the final page and capture its endCursor
    after = None
    conn = None
    while True:
        conn = (await _gql(client, ALBUMS_PAGE, first=50, after=after))["data"]["albums"]
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    assert 1 <= len(conn["edges"]) <= 50
    assert conn["pageInfo"]["hasNextPage"] is False

    tail = (
        await _gql(client, ALBUMS_PAGE, first=50, after=conn["pageInfo"]["endCursor"])
    )["data"]["albums"]
    assert tail["edges"] == []
    assert tail["pageInfo"]["hasNextPage"] is False
    assert tail["pageInfo"]["endCursor"] is None
    assert tail["pageInfo"]["startCursor"] is None


async def test_malformed_after_cursor_errors(client):
    body = await _gql(client, ALBUMS_PAGE, first=2, after="not-a-real-cursor")
    assert "errors" in body
    assert "Invalid 'after' cursor" in body["errors"][0]["message"]


async def test_first_over_cap_is_clamped(client):
    body = await _gql(client, ALBUMS_PAGE, first=100_000)
    assert "errors" not in body, body
    conn = body["data"]["albums"]
    assert len(conn["edges"]) == min(conn["totalCount"], 100)


@pytest.mark.parametrize(
    "query",
    [
        "query { albums(last: 2) { edges { node { slug } } } }",
        'query { albums(before: "x") { edges { node { slug } } } }',
    ],
)
async def test_backward_pagination_is_rejected(client, query):
    body = await _gql(client, query)
    assert "errors" in body
    assert "Backward pagination" in body["errors"][0]["message"]


async def test_node_refetch_round_trips(client):
    edge = (await _gql(client, ALBUMS_PAGE, first=1))["data"]["albums"]["edges"][0]
    gid = edge["node"]["id"]
    slug = edge["node"]["slug"]
    body = await _gql(
        client,
        "query ($id: ID!) { node(id: $id) { __typename ... on Album { slug } } }",
        id=gid,
    )
    assert "errors" not in body, body
    assert body["data"]["node"] == {"__typename": "Album", "slug": slug}


ALBUM_ITEMS_PAGE = """
query ($first: Int, $after: String) {
  album(slug: "in-rainbows") {
    items(first: $first, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { cursor node { __typename slug title } }
    }
  }
}
"""


async def test_album_items_are_paginated(client):
    page1 = (await _gql(client, ALBUM_ITEMS_PAGE, first=2))["data"]["album"]["items"]
    assert page1["totalCount"] == 4
    assert len(page1["edges"]) == 2
    assert page1["pageInfo"]["hasNextPage"] is True

    page2 = (
        await _gql(client, ALBUM_ITEMS_PAGE, first=2, after=page1["pageInfo"]["endCursor"])
    )["data"]["album"]["items"]
    assert len(page2["edges"]) == 2
    assert page2["pageInfo"]["hasNextPage"] is False

    s1 = [e["node"]["slug"] for e in page1["edges"]]
    s2 = [e["node"]["slug"] for e in page2["edges"]]
    assert set(s1).isdisjoint(s2)
    titles = [e["node"]["title"] for e in page1["edges"] + page2["edges"]]
    assert titles == sorted(titles)
