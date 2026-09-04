import strawberry

from miya_server.graphql.queries import Query
from miya_server.graphql.types.media_item import Photo, Song

schema = strawberry.Schema(query=Query, types=[Song, Photo])
