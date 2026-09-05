# Miya Server

Backend for the Miya iOS app: FastAPI + GraphQL (Strawberry) over PostgreSQL, with
self-hosted media (no third-party cloud storage). See
`/Users/hurtado/.claude/plans/let-s-make-a-plan-breezy-flamingo.md` for the full
architecture plan.

## Prerequisites

- Python 3.12 (managed automatically by `uv`)
- [`uv`](https://docs.astral.sh/uv/) — installed here via `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker Desktop, for the local Postgres via `docker-compose.yml`. If `docker`/
  `docker compose` aren't found after installing, its CLI lives in `~/.docker/bin`
  — add that to your `PATH` (already done for this machine's `~/.zshrc` and
  `~/.bash_profile`).

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
- Pagination: `albums` and `Album.items` are Relay connections — forward-only
  (`first` / `after`), opaque `(title, id)` keyset cursors, page size capped at 100.
  e.g. `albums(first: 20) { totalCount pageInfo { hasNextPage endCursor } edges { cursor node { slug items(first: 10) { edges { node { __typename slug } } } } } }`.
  `last` / `before` are rejected. Types implement the Relay `Node` interface, so
  `id` is an opaque global ID and `node(id: ID!)` refetches any album or media item.
- Search: `search(query: String!, sectionSlug: String, first: Int, after: String): SearchResult!`
  — fuzzy/typo-tolerant (`pg_trgm` GIN indexes on media title/subtitle/artist and
  album title/subtitle). `SearchResult.entries` is a forward Relay connection of
  matching `Song | Photo | Album`, ordered by trigram relevance then `id` (opaque
  `(score, id)` keyset cursors); `SearchResult.authors` is a small unpaginated list
  of authors whose `name` matched. `sectionSlug` (`"music"` / `"photos"`) scopes
  both to that section's membership. A media item also matches on its parent
  album's title. e.g.
  `search(query: "raidhead") { entries { edges { node { __typename ... on Song { title artist author { slug } album { slug } } } } } authors { slug name } }`.
- Authors: `Song.author` / `Photo.author` resolve an `Author { id slug name }`
  (Relay `Node`). Every song is credited to its artist; every photo to one
  synthetic photographer (`slug: "steven-hurtado"`) since the source fixtures
  carry no per-photo photographer. `node(id:)` refetches an author, and
  `Author.items(first:, after:)` is a forward Relay connection of that author's
  songs/photos across every album, keyed on `(title, id)`.
- Media files: `GET /media/{file_id}` — streams a self-hosted file (range-request
  support for audio scrubbing, long-lived cache headers since content is immutable)

### Ingesting real media

Once you have actual audio/photo files locally, match them to seeded rows by
filename (the stem must equal the item's or album's slug, e.g.
`weird-fishes.mp3`, `sunrise-ridge.jpg`, `in-rainbows.jpg` for an album cover):

```bash
uv run ingest-media --dir /path/to/your/media/files
```

This copies each file into `MEDIA_ROOT` (content-addressed by checksum — an
unchanged file re-ingests as a no-op; a changed one gets a new row rather than
overwriting in place), creates/reuses a `media_files` row, and backfills
`media_items.primary_media_file_id`, `songs.audio_file_id`,
`photos.image_file_id` (+ denormalized `photos.width`/`height`), or
`albums.cover_media_file_id` as appropriate. GraphQL `imageUrl`/`audioUrl`
fields then resolve to real `/media/{file_id}` URLs automatically.

## Tests

```bash
uv run pytest
```

Tests are split so they still run without a database:
- `test_health.py`, `test_graphql_schema.py` — no DB required, always run.
- `test_graphql_sections.py`, `test_graphql_albums.py`, `test_graphql_pagination.py`,
  `test_media_router.py`, `test_graphql_search.py`, `test_graphql_authors.py` —
  require Postgres; they auto-skip if `DATABASE_URL` isn't reachable, and seed the
  DB from the fixtures once (session-scoped) when it is.

## Project layout

See the plan doc above for the full rationale. Summary:

- `src/miya_server/db/` — SQLAlchemy models (`sections`, `albums`, `media_items` +
  `songs`/`photos` subtype tables, `media_files`, `section_items`/`section_albums`
  join tables).
- `migrations/` — Alembic migrations.
- `src/miya_server/seed/` — loads the Miya app's bundled `home_sections.json` /
  `albums.json` fixtures into Postgres (idempotent, upserts by slug). Does **not**
  create `media_files` rows — picsum URLs are dropped; real media is linked up by a
  separate ingest step once files exist locally (Phase 3). `authors.py` derives an
  `authors` row per artist (+ the synthetic photographer) and is shared by the
  seed and `bulk_generate.py`.
- `src/miya_server/graphql/` — Strawberry schema: `MediaItem` interface (`Song`/
  `Photo`), `AlbumRef`/`Album` types, `SectionEntry` union (`Song | Photo | Album`),
  and the `Query` type (`node(id)`, `sections`, `section(slug)`, `albums`,
  `album(slug)`, `search`). `Album`/`MediaItem`/`Author` implement the Relay
  `Node` interface; `albums`, `Album.items`, `Author.items` and `search.entries`
  return Relay connections. `types/author.py` holds the `Author` node +
  `Author.items` connection; `types/search.py` the `SearchResult` /
  `SearchEntryConnection`. `pagination.py` holds the shared keyset cursor helpers
  (`clamp_first`, `reject_backward`, `encode_cursor`/`decode_cursor`,
  `build_connection`). `context.py` wires a per-request DB session plus
  `album_loader` / `author_loader` DataLoaders so resolving many items'
  back-references stays N+1-safe.
- `src/miya_server/repositories/` — query layer between GraphQL resolvers and
  SQLAlchemy; batches song/photo/album lookups per section or album instead of
  querying per item.
- `src/miya_server/media/` — `router.py` (`GET /media/{file_id}`), `storage.py`
  (media URL construction), `ingest.py` (the `ingest-media` CLI).

## Not yet built

Many-to-many album membership (skipped until the library needs it), album
authorship (`Album.author` — only songs/photos carry `author_id` today), and
mutations/auth (deferred until real auth is designed). `sections` /
`Section.items` are still unpaginated — the curated section content is
intentionally bounded.
