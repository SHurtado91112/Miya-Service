import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


_SECTIONS_QUERY = """
query {
  sections {
    slug
    title
    items {
      __typename
      ... on Song { slug title artist }
      ... on Photo { slug title }
      ... on Album { slug title }
    }
  }
}
"""


async def test_sections_returns_music_and_photos(client):
    response = await client.post("/graphql", json={"query": _SECTIONS_QUERY})
    assert response.status_code == 200
    body = response.json()
    assert "errors" not in body, body

    sections = {s["slug"]: s for s in body["data"]["sections"]}
    assert set(sections) == {"music", "photos"}

    music_items = sections["music"]["items"]
    typenames = {item["__typename"] for item in music_items}
    assert "Song" in typenames
    assert "Album" in typenames
    album_titles = {item["title"] for item in music_items if item["__typename"] == "Album"}
    assert "In Rainbows" in album_titles


async def test_section_folds_album_members(client):
    response = await client.post("/graphql", json={"query": _SECTIONS_QUERY})
    body = response.json()
    assert "errors" not in body, body
    music_items = {s["slug"]: s for s in body["data"]["sections"]}["music"]["items"]

    album_slugs = {i["slug"] for i in music_items if i["__typename"] == "Album"}
    song_slugs = {i["slug"] for i in music_items if i["__typename"] == "Song"}
    # "weird-fishes" is a music section_item whose album ("in-rainbows") is also
    # a card in the section -> it folds into the card.
    assert "in-rainbows" in album_slugs
    assert "weird-fishes" not in song_slugs


async def test_section_by_slug(client):
    query = """
    query {
      section(slug: "photos") {
        title
        items { __typename }
      }
    }
    """
    response = await client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["section"]["title"] == "Photos"
    assert len(body["data"]["section"]["items"]) > 0


async def test_unknown_section_returns_null(client):
    query = 'query { section(slug: "does-not-exist") { title } }'
    response = await client.post("/graphql", json={"query": query})
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["section"] is None
