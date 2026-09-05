import strawberry
from strawberry.schema.config import StrawberryConfig

from miya_server.graphql.pagination import MAX_PAGE_SIZE
from miya_server.graphql.queries import Query
from miya_server.graphql.types.album import Album
from miya_server.graphql.types.author import Author
from miya_server.graphql.types.media_item import Photo, Song

schema = strawberry.Schema(
    query=Query,
    types=[Song, Photo, Album, Author],
    config=StrawberryConfig(relay_max_results=MAX_PAGE_SIZE),
)
