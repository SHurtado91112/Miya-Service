from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from miya_server.graphql.context import get_context
from miya_server.graphql.schema import schema
from miya_server.media.router import router as media_router

app = FastAPI(title="Miya Server")

graphql_router = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_router, prefix="/graphql")
app.include_router(media_router, prefix="/media")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
