import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")

SEARCH_QUERY = """
query($q: String!) {
  searchMedia(query: $q) {
    __typename
    title
    ... on Song { artist }
  }
}
"""


async def test_search_exact_title_match(client):
    response = await client.post("/graphql", json={"query": SEARCH_QUERY, "variables": {"q": "Midnight City"}})
    body = response.json()
    assert "errors" not in body, body
    titles = [item["title"] for item in body["data"]["searchMedia"]]
    assert "Midnight City" in titles


async def test_search_by_artist(client):
    response = await client.post("/graphql", json={"query": SEARCH_QUERY, "variables": {"q": "Radiohead"}})
    body = response.json()
    assert "errors" not in body, body
    titles = {item["title"] for item in body["data"]["searchMedia"]}
    # Multiple Radiohead songs are seeded across home_sections.json + albums.json.
    assert "Pyramid Song" in titles
    assert "Weird Fishes / Arpeggi" in titles


async def test_search_tolerates_typo(client):
    # pg_trgm's default similarity threshold (0.3) should still match a
    # one-character typo in a short-ish title.
    response = await client.post(
        "/graphql", json={"query": SEARCH_QUERY, "variables": {"q": "Redbne"}}
    )
    body = response.json()
    assert "errors" not in body, body
    titles = [item["title"] for item in body["data"]["searchMedia"]]
    assert "Redbone" in titles


async def test_search_no_match_returns_empty_list(client):
    response = await client.post(
        "/graphql", json={"query": SEARCH_QUERY, "variables": {"q": "zzzzzznonexistentzzzz"}}
    )
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["searchMedia"] == []


async def test_search_blank_query_returns_empty_list(client):
    response = await client.post("/graphql", json={"query": SEARCH_QUERY, "variables": {"q": "   "}})
    body = response.json()
    assert "errors" not in body, body
    assert body["data"]["searchMedia"] == []
