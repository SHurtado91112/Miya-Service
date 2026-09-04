import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def test_albums_lists_all_albums(client):
    query = "query { albums { slug title } }"
    response = await client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    slugs = {a["slug"] for a in body["data"]["albums"]}
    assert {"in-rainbows", "yesterday-morning"} <= slugs


async def test_album_detail_by_slug(client):
    query = """
    query {
      album(slug: "in-rainbows") {
        title
        items {
          __typename
          ... on Song {
            title
            album { slug title }
          }
        }
      }
    }
    """
    response = await client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    album = body["data"]["album"]
    assert album["title"] == "In Rainbows"
    titles = {item["title"] for item in album["items"]}
    assert "Weird Fishes / Arpeggi" in titles
    for item in album["items"]:
        assert item["album"]["slug"] == "in-rainbows"


async def test_unknown_album_returns_null(client):
    query = 'query { album(slug: "does-not-exist") { title } }'
    response = await client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["album"] is None
