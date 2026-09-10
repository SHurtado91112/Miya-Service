"""End-to-end: ingest an author portrait, then check that `Author.imageUrl` /
`Author.thumbnailUrl` are exposed through GraphQL and resolve to fetchable
`/media/...` URLs. Kept separate from test_graphql_authors.py so that module
stays a pure query-against-seed suite with no filesystem writes.
"""

import uuid

import pytest
from conftest import signed
from PIL import Image
from sqlalchemy import select

from miya_server.config import Settings
from miya_server.db.base import async_session_factory
from miya_server.db.models import Author, MediaFile
from miya_server.media import ingest

pytestmark = pytest.mark.usefixtures("seeded_db")


async def _gql(authed_client, query, **variables):
    response = await authed_client.post(
        "/graphql", json={"query": query, "variables": variables or {}}
    )
    body = response.json()
    assert "errors" not in body, body
    return body["data"]


RADIOHEAD_AUTHOR_ID = """
query {
  section(slug: "music") {
    items { __typename ... on Song { author { id slug } } }
  }
}
"""

AUTHOR_IMAGE_NODE = """
query ($id: ID!) {
  node(id: $id) { ... on Author { slug imageUrl thumbnailUrl } }
}
"""


async def test_author_portrait_flows_through_graphql(authed_client, tmp_path, monkeypatch):
    settings_override = Settings(media_root=tmp_path / "media_root")
    monkeypatch.setattr(ingest, "get_settings", lambda: settings_override)
    monkeypatch.setattr("miya_server.media.router.get_settings", lambda: settings_override)

    Image.new("RGB", (1000, 1000), color=(200, 120, 80)).save(
        tmp_path / "author-radiohead.jpg", format="JPEG"
    )
    await ingest.run(tmp_path)

    data = await _gql(authed_client, RADIOHEAD_AUTHOR_ID)
    author_id = next(
        i["author"]["id"]
        for i in data["section"]["items"]
        if i["__typename"] == "Song" and i["author"] and i["author"]["slug"] == "radiohead"
    )

    async with async_session_factory() as session:
        file_id = (
            await session.execute(select(Author).where(Author.slug == "radiohead"))
        ).scalar_one().profile_media_file_id

    try:
        node = (await _gql(authed_client, AUTHOR_IMAGE_NODE, id=author_id))["node"]
        # Signed now: the path is still the contract, the query carries exp+sig.
        assert f"/media/{file_id}?" in node["imageUrl"]
        assert f"/media/{file_id}/thumb?" in node["thumbnailUrl"]

        # Both URLs are live (path portion served by our own media router).
        assert (await authed_client.get(signed(f"/media/{file_id}"))).status_code == 200
        thumb = await authed_client.get(signed(f"/media/{file_id}/thumb"))
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/webp"
    finally:
        async with async_session_factory() as session:
            author = (
                await session.execute(select(Author).where(Author.slug == "radiohead"))
            ).scalar_one()
            author.profile_media_file_id = None
            await session.flush()
            mf = await session.get(MediaFile, uuid.UUID(str(file_id)))
            if mf is not None:
                await session.delete(mf)
            await session.commit()
