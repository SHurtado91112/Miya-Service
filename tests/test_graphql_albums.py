import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def test_albums_connection_paginates_over_all_seed_albums(authed_client):
    query = """
    query ($after: String) {
      albums(first: 100, after: $after) {
        totalCount
        pageInfo { hasNextPage endCursor }
        edges { node { slug } }
      }
    }
    """
    slugs: set[str] = set()
    after = None
    total = None
    while True:
        body = (await authed_client.post("/graphql", json={"query": query, "variables": {"after": after}})).json()
        assert "errors" not in body, body
        conn = body["data"]["albums"]
        total = conn["totalCount"]
        slugs.update(e["node"]["slug"] for e in conn["edges"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]

    assert {"in-rainbows", "yesterday-morning"} <= slugs
    assert len(slugs) == total


async def test_album_detail_by_slug(authed_client):
    query = """
    query {
      album(slug: "in-rainbows") {
        title
        items(first: 50) {
          totalCount
          edges {
            node {
              __typename
              ... on Song {
                title
                album { slug title }
              }
            }
          }
        }
      }
    }
    """
    response = await authed_client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    album = body["data"]["album"]
    assert album["title"] == "In Rainbows"
    nodes = [edge["node"] for edge in album["items"]["edges"]]
    titles = {node["title"] for node in nodes}
    assert "Weird Fishes / Arpeggi" in titles
    assert album["items"]["totalCount"] == len(nodes)
    for node in nodes:
        assert node["album"]["slug"] == "in-rainbows"


async def test_album_exposes_its_representative_author(authed_client):
    query = """
    query {
      album(slug: "in-rainbows") {
        author { slug name }
        items(first: 1) {
          edges { node { ... on Song { author { slug name } } } }
        }
      }
    }
    """
    body = (await authed_client.post("/graphql", json={"query": query})).json()
    assert "errors" not in body, body
    album = body["data"]["album"]
    assert album["author"] is not None
    # The album's author is the one credited on its items.
    item_author = album["items"]["edges"][0]["node"]["author"]
    assert album["author"] == item_author


async def test_unknown_album_returns_null(authed_client):
    query = 'query { album(slug: "does-not-exist") { title } }'
    response = await authed_client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["album"] is None
