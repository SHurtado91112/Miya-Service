"""Schema-shape tests that don't require a live database -- verifies the
GraphQL contract (types/fields the iOS client will rely on) independent of
data. See test_graphql_sections.py / test_graphql_albums.py /
test_graphql_pagination.py for query tests against real seeded data (require
Postgres)."""

from miya_server.graphql.schema import schema


def test_query_type_has_expected_fields():
    query_type = schema.schema_converter.type_map["Query"]
    field_names = {field.name for field in query_type.definition.fields}
    assert {"sections", "section", "albums", "album", "node", "search"} <= field_names


def test_search_field_shape():
    sdl = schema.as_str()
    assert "type SearchResult" in sdl
    assert "entries: SearchEntryConnection!" in sdl
    assert "authors: [Author!]!" in sdl
    assert "type SearchEntryConnection" in sdl
    assert "node: SectionEntry!" in sdl  # SearchEntryEdge carries the union

    query_type = schema.schema_converter.type_map["Query"]
    search_field = next(f for f in query_type.definition.fields if f.name == "search")
    arg_names = {arg.python_name for arg in search_field.arguments}
    assert {"query", "section_slug", "first", "after", "before", "last"} <= arg_names


def test_author_is_a_node_with_a_relay_item_connection():
    sdl = schema.as_str()
    assert "type Author implements Node" in sdl
    assert "type AuthorItemConnection" in sdl
    assert "author: Author" in sdl  # Song / Photo back-link

    author_type = schema.schema_converter.type_map["Author"]
    items_field = next(f for f in author_type.definition.fields if f.name == "items")
    arg_names = {arg.python_name for arg in items_field.arguments}
    assert {"first", "after", "before", "last"} <= arg_names


def test_section_entry_union_includes_song_photo_album():
    union_type = schema.schema_converter.type_map["SectionEntry"]
    type_names = {t.name for t in union_type.implementation.types}
    assert type_names == {"Song", "Photo", "Album"}


def test_song_and_photo_implement_media_item_and_node():
    sdl = schema.as_str()
    assert "type Song implements MediaItem & Node" in sdl
    assert "type Photo implements MediaItem & Node" in sdl
    assert "interface MediaItem implements Node" in sdl
    assert "type Album implements Node" in sdl


def test_albums_is_a_relay_connection():
    sdl = schema.as_str()
    assert "type AlbumConnection" in sdl
    assert "type AlbumEdge" in sdl
    assert "type MediaItemConnection" in sdl
    assert "type PageInfo" in sdl

    query_type = schema.schema_converter.type_map["Query"]
    albums_field = next(f for f in query_type.definition.fields if f.name == "albums")
    arg_names = {arg.python_name for arg in albums_field.arguments}
    assert {"first", "after", "before", "last"} <= arg_names

    album_type = schema.schema_converter.type_map["Album"]
    items_field = next(f for f in album_type.definition.fields if f.name == "items")
    item_arg_names = {arg.python_name for arg in items_field.arguments}
    assert {"first", "after", "before", "last"} <= item_arg_names
