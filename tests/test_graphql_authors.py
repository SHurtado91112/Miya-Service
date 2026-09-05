"""End-to-end tests for the `Author` node: the `author` back-link on
Song/Photo, the paginated `Author.items` connection, and `node(id:)` refetch.
"""

import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def _gql(client, query, **variables):
    response = await client.post(
        "/graphql", json={"query": query, "variables": variables or {}}
    )
    body = response.json()
    assert "errors" not in body, body
    return body["data"]


SONG_AUTHOR = """
query {
  section(slug: "music") {
    items {
      __typename
      ... on Song { slug title author { id slug name } }
    }
  }
}
"""


async def test_song_exposes_its_author(client):
    data = await _gql(client, SONG_AUTHOR)
    songs = [i for i in data["section"]["items"] if i["__typename"] == "Song"]
    radiohead_songs = [s for s in songs if s["author"] and s["author"]["slug"] == "radiohead"]
    assert radiohead_songs
    assert radiohead_songs[0]["author"]["name"] == "Radiohead"
    assert radiohead_songs[0]["author"]["id"]  # opaque global id present


PHOTO_AUTHOR = """
query {
  section(slug: "photos") {
    items {
      __typename
      ... on Photo { slug author { slug name } }
    }
  }
}
"""


async def test_photo_has_the_synthetic_photographer(client):
    data = await _gql(client, PHOTO_AUTHOR)
    photos = [i for i in data["section"]["items"] if i["__typename"] == "Photo"]
    assert photos
    assert all(p["author"]["slug"] == "steven-hurtado" for p in photos)
    assert all(p["author"]["name"] == "Steven Hurtado" for p in photos)


AUTHOR_NODE = """
query ($id: ID!, $first: Int, $after: String) {
  node(id: $id) {
    __typename
    ... on Author {
      id
      slug
      name
      items(first: $first, after: $after) {
        totalCount
        pageInfo { hasNextPage endCursor }
        edges { cursor node { __typename slug title } }
      }
    }
  }
}
"""


async def _radiohead_author_id(client) -> str:
    data = await _gql(client, SONG_AUTHOR)
    for item in data["section"]["items"]:
        if item["__typename"] == "Song" and item["author"] and item["author"]["slug"] == "radiohead":
            return item["author"]["id"]
    raise AssertionError("no Radiohead song with an author in the music section")


async def test_author_node_refetch_and_items_pagination(client):
    author_id = await _radiohead_author_id(client)

    page1 = (await _gql(client, AUTHOR_NODE, id=author_id, first=3))["node"]
    assert page1["__typename"] == "Author"
    assert page1["slug"] == "radiohead"
    assert page1["items"]["totalCount"] >= 5  # In Rainbows + loose Radiohead tracks
    assert len(page1["items"]["edges"]) == 3
    assert page1["items"]["pageInfo"]["hasNextPage"] is True

    page2 = (
        await _gql(
            client,
            AUTHOR_NODE,
            id=author_id,
            first=3,
            after=page1["items"]["pageInfo"]["endCursor"],
        )
    )["node"]
    s1 = [e["node"]["slug"] for e in page1["items"]["edges"]]
    s2 = [e["node"]["slug"] for e in page2["items"]["edges"]]
    assert set(s1).isdisjoint(s2)
    titles = [e["node"]["title"] for e in page1["items"]["edges"] + page2["items"]["edges"]]
    assert titles == sorted(titles)


async def test_author_items_reject_backward_pagination(client):
    author_id = await _radiohead_author_id(client)
    response = await client.post(
        "/graphql",
        json={
            "query": AUTHOR_NODE.replace("$after: String", "$after: String, $last: Int").replace(
                "after: $after", "after: $after, last: $last"
            ),
            "variables": {"id": author_id, "last": 2},
        },
    )
    body = response.json()
    assert body.get("errors")
    assert "Backward pagination" in body["errors"][0]["message"]
