import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def test_sections_returns_music_and_photos(client):
    query = """
    query {
      sections {
        slug
        title
        items {
          __typename
          ... on Song { title artist }
          ... on Photo { title }
          ... on Album { title }
        }
      }
    }
    """
    response = await client.post("/graphql", json={"query": query})
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
