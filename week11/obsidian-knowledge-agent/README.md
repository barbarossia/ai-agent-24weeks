# Week 11 — Obsidian knowledge agent

A uv-managed CLI that reads one named Markdown file, reuses Week 9 chunking and embedding interfaces, and stores/searches vectors through live psycopg SQL. There is no directory scan or implicit vault synchronization.

## Setup

Run these commands from `week11/obsidian-knowledge-agent` in the repository checkout (Python 3.12+ and uv required):

```powershell
uv sync --locked
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '5432'
$env:PGDATABASE = 'knowledge'
$env:PGUSER = 'postgres'
# Supply PGPASSWORD securely through your session or use a protected libpq password file.
# Alternatively set W11_DATABASE_URL through your secret manager; do not commit it.
$env:W11_PROVIDER = 'mock'
$env:W11_DIMENSION = '128'
uv run obsidian-agent init
uv run obsidian-agent check
```

The Week 9 project is an editable local path dependency at `../../week9/vector-search-lab`; no Week 9 source is copied or modified. A standalone copy of only this directory cannot resolve that dependency. Week 9's demo/in-memory PgVectorStore is not used.

Connection configuration uses `W11_DATABASE_URL` or standard libpq environment variables (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGPASSFILE`). Never put credentials in command arguments, source, or evidence. Errors suppress driver/provider details because those can include secrets.

## Migration and configuration

`init` executes packaged `migrations/001_initial.sql` in a transaction: `CREATE EXTENSION IF NOT EXISTS vector`, task schema `week11_obsidian_agent`, and `settings`, `documents`, `chunks` tables. The role needs extension/schema creation privileges for initialization; normal operations need table privileges. An existing schema without this migration's ownership marker is rejected. Repeated initialization checks existing objects; it does not repair, drop, or overwrite them.

`check` verifies ownership marker, extension, required columns/types/nullability, document/chunk primary keys, unique source and chunk position, cascading foreign key, nonempty source constraint, migration version, vector dimension and provider identity. A mismatch requires inspecting configuration and existing data; this MVP has no automatic dimension migration. Provider/model changes, even at the same dimension, are rejected by stored provider identity. Endpoint identity is hashed. The owner marker prevents accidental reuse, not malicious tampering.

Default `mock` uses Week 9 MockEmbeddingProvider with 128 dimensions (configurable via `W11_DIMENSION`). **Mock vectors validate pipeline/database behavior only; they do not establish semantic retrieval quality.** Empty/zero, nonfinite and wrong-dimension vectors are rejected for meaningful cosine operations.

Optional `W11_PROVIDER=openai` reuses Week 9 OpenAIEmbeddingProvider. Set `W11_API_KEY`, `W11_MODEL` (default `text-embedding-3-small`), `W11_BASE_URL` (default `https://api.openai.com/v1`), and `W11_DIMENSION` (default 1536). The endpoint must implement the OpenAI embeddings format, return embeddings in input order and emit the configured dimension. Week 9 does not send a dimensions override; configure the model's actual output size. This path may incur charges, is not used by automated tests, and has not been validated against a real service. Switching an initialized mock corpus to a real model requires a separately planned migration/re-embedding, not just changing environment variables.

## Fixture-only example

```powershell
$source = 'integration-test/' + [guid]::NewGuid().ToString() + '/note.md'
uv run obsidian-agent index tests/fixtures/note.md --source-path $source
uv run obsidian-agent index tests/fixtures/note.md --source-path $source
uv run obsidian-agent search 'cosine retrieval' --top-k 2 --source-path $source --tag postgres --tag retrieval
uv run obsidian-agent delete $source
```

`index FILE` accepts exactly one existing `.md` file. `--source-path` supplies a logical source identity while reading only FILE; omit it to use the absolute resolved path with forward slashes. Keep that identity stable across updates. Deletion accepts the exact indexed source identity, not a directory. It removes one document and its chunks through the foreign key; missing documents return zero. Missing files are never deleted implicitly.

Frontmatter is a YAML mapping. Title priority: frontmatter `title`, first H1, filename stem. Tags accept a YAML string list or a comma/whitespace separated string; leading `#` is removed, duplicates removed, and case preserved. Tags are frontmatter only; inline hashtags/wikilinks/embeds are not expanded. The body excludes frontmatter. Metadata stores title, tags, filesystem UTC modified time, raw-file SHA-256 and indexed time. Document IDs hash the exact source identity; Week 9 chunk IDs combine that ID with chunk index. Week 9 heading breadcrumbs are preserved. Its heading parser is intentionally basic, including its behavior around fenced code and headings deeper than level four.

Identical content hashes skip embeddings and data writes (a changed mtime alone does not update stored metadata). Changed content replaces metadata and all chunks in one transaction; SQL or embedding failure leaves the old document intact. An advisory lock serializes index/delete operations on the same ID. Chunk positions are stable, not semantic identities across edits. Empty bodies can store metadata with no chunks. Embedding computation occurs inside the update transaction to keep this simple MVP atomic; large/remote workloads would benefit from a staged design.

Search performs exact PostgreSQL cosine distance ordering, with `similarity = 1 - distance`, and deterministic chunk-ID ties. `--top-k` is 1–1000. Source filters are exact case-sensitive matches. Repeated `--tag` values use **ANY** exact case-sensitive overlap; a source filter and tag filter combine with AND. Empty tag lists mean no tag filter. Output JSON contains content, similarity, source path, heading breadcrumb, tags and chunk ID. Tags passed to search must use normalized stored spelling (e.g. `postgres`, not `#postgres`).

No HNSW or IVFFlat index is created: exact search is sufficient for the small corpus. At larger scale, benchmark recall/latency before adding an approximate index and plan dimension/operator compatibility separately.

## Validation

```powershell
# Offline: no database, network, account, or paid embedding service
uv run pytest -m 'not integration' -q
# Live: initialize/check the task schema first, then explicitly opt in
$env:W11_RUN_INTEGRATION = '1'
uv run pytest -m integration -q
Remove-Item Env:W11_RUN_INTEGRATION
```

Default `uv run pytest` runs offline tests and skips live tests. Live tests require the mock 128-dimensional schema, use only `tests/fixtures/note.md` and one explicitly created changed-note fixture, and allocate unique `integration-test/<uuid>/note.md` source identities per test. They validate SQL search/filter provenance, no-call unchanged indexing, update rollback after an injected SQL constraint violation, replacement, configuration mismatch, and cascade isolation. Cleanup deletes only each run's exact source identities. Tests never drop/truncate objects or touch other schemas; interrupted processes can leave identifiable records, which must be removed individually by exact identity. Schema initialization is explicit, not performed by tests. The offline transaction harness exercises control flow; only the opt-in suite establishes actual PostgreSQL transaction behavior.
