# Miya Server

Backend for the Miya iOS app: FastAPI + GraphQL (Strawberry) over PostgreSQL, with
self-hosted media (no third-party cloud storage). See
`/Users/hurtado/.claude/plans/let-s-make-a-plan-breezy-flamingo.md` for the full
architecture plan.

## Prerequisites

- Python 3.12 (managed automatically by `uv`)
- [`uv`](https://docs.astral.sh/uv/) — installed here via `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker (for the local Postgres via `docker-compose.yml`) — **not currently installed
  in this dev environment**. Install Docker Desktop, or point `DATABASE_URL` at any
  Postgres 13+ instance you already have running (Postgres.app, a Homebrew install
  once fixed, a remote dev DB, etc).

## Local setup

```bash
cp .env.example .env          # adjust DATABASE_URL/MEDIA_ROOT/PUBLIC_BASE_URL if needed
docker compose up -d          # starts Postgres with pg_stat_statements enabled
uv run alembic upgrade head   # creates the schema
uv run seed                   # loads sections/albums/media_items from the Miya app's mock JSON
uv run uvicorn miya_server.main:app --reload
```

Or just run `scripts/dev.sh`, which does all of the above.

- Health check: `GET /health`
- GraphQL API: `/graphql` (GraphiQL UI in the browser, e.g. `sections { title items { __typename ... on Song { title } ... on Photo { title } ... on Album { title } } }`)
- Media files (Phase 3): `/media/{file_id}` — not yet implemented

## Tests

```bash
uv run pytest
```

Tests are split so they still run without a database:
- `test_health.py`, `test_graphql_schema.py` — no DB required, always run.
- `test_graphql_sections.py`, `test_graphql_albums.py` — require Postgres; they
  auto-skip if `DATABASE_URL` isn't reachable, and seed the DB from the fixtures
  once (session-scoped) when it is.

## Project layout

See the plan doc above for the full rationale. Summary:

- `src/miya_server/db/` — SQLAlchemy models (`sections`, `albums`, `media_items` +
  `songs`/`photos` subtype tables, `media_files`, `section_items`/`section_albums`
  join tables).
- `migrations/` — Alembic migrations.
- `src/miya_server/seed/` — loads the Miya app's bundled `home_sections.json` /
  `albums.json` fixtures into Postgres (idempotent, upserts by slug). Does **not**
  create `media_files` rows — picsum URLs are dropped; real media is linked up by a
  separate ingest step once files exist locally (Phase 3).
- `src/miya_server/graphql/` — Strawberry schema: `MediaItem` interface (`Song`/
  `Photo`), `AlbumRef`/`Album` types, `SectionEntry` union (`Song | Photo | Album`),
  and the `Query` type (`sections`, `section(slug)`, `albums`, `album(slug)`).
  `context.py` wires a per-request DB session plus an `album_loader` DataLoader so
  resolving many items' back-reference to their album stays N+1-safe.
- `src/miya_server/repositories/` — query layer between GraphQL resolvers and
  SQLAlchemy; batches song/photo/album lookups per section or album instead of
  querying per item.
- `src/miya_server/media/` — media URL helper only so far; the actual file-serving
  route is Phase 3.
