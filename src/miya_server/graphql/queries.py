import strawberry

from miya_server.graphql.types.album import Album, build_album
from miya_server.graphql.types.section import Section, build_section_entries
from miya_server.repositories import albums as albums_repo
from miya_server.repositories import sections as sections_repo


async def _build_section(session, db_section) -> Section:
    entries = await sections_repo.list_section_entries(session, db_section.id)
    items = await build_section_entries(session, entries)
    return Section(
        id=strawberry.ID(str(db_section.id)),
        slug=db_section.slug,
        title=db_section.title,
        items=items,
    )


@strawberry.type
class Query:
    @strawberry.field
    async def sections(self, info: strawberry.Info) -> list[Section]:
        session = info.context.session
        db_sections = await sections_repo.list_sections(session)
        return [await _build_section(session, db_section) for db_section in db_sections]

    @strawberry.field
    async def section(self, info: strawberry.Info, slug: str) -> Section | None:
        session = info.context.session
        db_section = await sections_repo.get_section_by_slug(session, slug)
        if db_section is None:
            return None
        return await _build_section(session, db_section)

    @strawberry.field
    async def albums(self, info: strawberry.Info) -> list[Album]:
        session = info.context.session
        db_albums = await albums_repo.list_albums(session)
        return [build_album(db_album) for db_album in db_albums]

    @strawberry.field
    async def album(self, info: strawberry.Info, slug: str) -> Album | None:
        session = info.context.session
        db_album = await albums_repo.get_album_by_slug(session, slug)
        return build_album(db_album) if db_album else None
