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
    album_slugs = {
        e["node"]["slug"]
        for e in data["entries"]["edges"]
        if e["node"]["__typename"] == "Album"
    }
    # "In Rainbows" (subtitle "Radiohead") matches, so its members fold into the
    # album card; a Radiohead track with no album stays as its own row.
    assert "Pyramid Song" in titles
    assert "Weird Fishes / Arpeggi" not in titles
    assert "in-rainbows" in album_slugs
    # The Radiohead author is surfaced alongside the entries.
    assert any(a["slug"] == "radiohead" for a in data["authors"])


async def test_search_tolerates_typo(client):
    data = await _search(client, "Redbne")
    titles = [e["node"]["title"] for e in data["entries"]["edges"]]
    assert "Redbone" in titles


async def test_search_folds_members_into_matched_album(client):
    # "In Rainbows" matches "rainbows"; its members (e.g. "weird-fishes") fold
    # into the album card rather than appearing as their own rows.
    data = await _search(client, "rainbows")
    slugs_by_type: dict[str, set[str]] = {}
    for e in data["entries"]["edges"]:
        slugs_by_type.setdefault(e["node"]["__typename"], set()).add(e["node"]["slug"])
    assert "in-rainbows" in slugs_by_type.get("Album", set())
    assert "weird-fishes" not in slugs_by_type.get("Song", set())


async def test_search_returns_bare_song_when_its_album_is_not_a_match(client):
    # "weird fishes" matches the song's own title but not its album "In Rainbows",
    # so the song is returned directly (nothing to fold it into).
    data = await _search(client, "weird fishes")
    songs = {
        e["node"]["slug"]
        for e in data["entries"]["edges"]
        if e["node"]["__typename"] == "Song"
    }
    assert "weird-fishes" in songs


async def test_search_returns_album_cards(client):
    data = await _search(client, "In Rainbows")
    slugs_by_type: dict[str, set[str]] = {}
    for e in data["entries"]["edges"]:
        slugs_by_type.setdefault(e["node"]["__typename"], set()).add(e["node"]["slug"])
    assert "in-rainbows" in slugs_by_type.get("Album", set())
    # Members are folded away, not listed alongside the card.
    assert slugs_by_type.get("Song", set()).isdisjoint(
        {"15-step", "weird-fishes", "reckoner", "jigsaw-falling-into-place"}
    )


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
