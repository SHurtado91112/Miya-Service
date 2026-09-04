"""Schema-shape tests that don't require a live database -- verifies the
GraphQL contract (types/fields the iOS client will rely on) independent of
data. See test_graphql_sections.py / test_graphql_albums.py for query tests
against real seeded data (require Postgres)."""

from miya_server.graphql.schema import schema


def test_query_type_has_expected_fields():
    query_type = schema.schema_converter.type_map["Query"]
    field_names = {field.name for field in query_type.definition.fields}
    assert {"sections", "section", "albums", "album"} <= field_names


def test_section_entry_union_includes_song_photo_album():
    union_type = schema.schema_converter.type_map["SectionEntry"]
    type_names = {t.name for t in union_type.implementation.types}
    assert type_names == {"Song", "Photo", "Album"}


def test_song_and_photo_implement_media_item_interface():
    sdl = schema.as_str()
    assert "type Song implements MediaItem" in sdl
    assert "type Photo implements MediaItem" in sdl
