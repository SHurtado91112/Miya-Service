import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")

SEARCH_QUERY = """
query($q: String!, $section: String, $first: Int, $after: String) {
  search(query: $q, sectionSlug: $section, first: $first, after: $after) {
    entries {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        cursor
        node {
          __typename
          ... on Song  { title slug artist album { slug } author { slug name } }
          ... on Photo { title slug author { slug name } }
          ... on Album { title slug }
        }
      }
    }
    authors { slug name }
  }
}
"""


async def _search(client, q, **variables):
    response = await client.post(
        "/graphql", json={"query": SEARCH_QUERY, "variables": {"q": q, **variables}}
    )
    body = response.json()
    assert "errors" not in body, body
    return body["data"]["search"]


async def test_search_exact_title_match(client):
    data = await _search(client, "Midnight City")
    titles = [e["node"]["title"] for e in data["entries"]["edges"]]
    assert "Midnight City" in titles


async def test_search_by_artist_matches_songs_and_author(client):
    data = await _search(client, "Radiohead")
    titles = {e["node"]["title"] for e in data["entries"]["edges"]}
    assert "Pyramid Song" in titles
    assert "Weird Fishes / Arpeggi" in titles
    # The Radiohead author is surfaced alongside the entries.
    assert any(a["slug"] == "radiohead" for a in data["authors"])


async def test_search_tolerates_typo(client):
    data = await _search(client, "Redbne")
    titles = [e["node"]["title"] for e in data["entries"]["edges"]]
    assert "Redbone" in titles


async def test_search_matches_by_parent_album_title(client):
    # "Weird Fishes / Arpeggi" doesn't contain "rainbows" -- it matches because
    # its parent album is "In Rainbows".
    data = await _search(client, "rainbows")
    songs = {
        e["node"]["slug"]
        for e in data["entries"]["edges"]
        if e["node"]["__typename"] == "Song"
    }
    assert "weird-fishes" in songs


async def test_search_returns_album_cards(client):
    data = await _search(client, "In Rainbows")
    albums = {
        e["node"]["slug"]
        for e in data["entries"]["edges"]
        if e["node"]["__typename"] == "Album"
    }
    assert "in-rainbows" in albums


async def test_search_photos_have_the_synthetic_photographer(client):
    data = await _search(client, "Ridge", section="photos")
    photos = [
        e["node"] for e in data["entries"]["edges"] if e["node"]["__typename"] == "Photo"
    ]
    assert photos
    assert all(p["author"]["slug"] == "steven-hurtado" for p in photos)


async def test_search_section_scope_excludes_other_sections(client):
    music = await _search(client, "Radiohead", section="music")
    photos = await _search(client, "Radiohead", section="photos")
    assert music["entries"]["totalCount"] > 0
    assert photos["entries"]["totalCount"] == 0


async def test_search_pagination_is_forward_keyset(client):
    page1 = await _search(client, "Radiohead", first=2)
    assert len(page1["entries"]["edges"]) <= 2
    if page1["entries"]["pageInfo"]["hasNextPage"]:
        cursor = page1["entries"]["pageInfo"]["endCursor"]
        page2 = await _search(client, "Radiohead", first=2, after=cursor)
        p1_slugs = {e["node"]["slug"] for e in page1["entries"]["edges"]}
        p2_slugs = {e["node"]["slug"] for e in page2["entries"]["edges"]}
        assert p1_slugs.isdisjoint(p2_slugs)


async def test_search_ranks_exact_title_first(client):
    # Even with the bulk corpus loaded (many "Midnight *" albums matching on
    # album-title), the exact-title song outranks them.
    data = await _search(client, "Midnight City", first=1)
    assert data["entries"]["edges"][0]["node"]["title"] == "Midnight City"


async def test_search_blank_query_is_empty(client):
    data = await _search(client, "   ")
    assert data["entries"]["edges"] == []
    assert data["entries"]["totalCount"] == 0
    assert data["authors"] == []


async def test_search_no_match_is_empty(client):
    data = await _search(client, "zzzzzznonexistentzzzz")
    assert data["entries"]["edges"] == []
    assert data["authors"] == []
