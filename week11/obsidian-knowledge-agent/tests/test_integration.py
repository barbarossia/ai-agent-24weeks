"""No init/DDL in tests: explicitly initialize the task schema before opting in."""

import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

import psycopg
import pytest
from vector_search_lab.embeddings import MockEmbeddingProvider

from obsidian_knowledge_agent.ingestion import read_note
from obsidian_knowledge_agent.store import PgStore, SCHEMA, SchemaMismatch

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv("W11_RUN_INTEGRATION") != "1", reason="Set W11_RUN_INTEGRATION=1 to opt into local DB tests")]
FIXTURE = Path(__file__).parent / "fixtures/note.md"


@pytest.fixture
def db():
    store = PgStore.connect(os.getenv("W11_DATABASE_URL", ""))
    store.check()
    sources = [f"integration-test/{uuid4()}/note.md" for _ in range(2)]
    try:
        yield store, sources
    finally:
        for source in sources:
            store.delete(source)
        store.close()


def test_schema_and_configuration(db):
    store, _ = db
    assert store.check()["dimension"] == 128
    for dimension, identity in [(64, store.provider_id), (128, "different-provider")]:
        with pytest.raises(SchemaMismatch):
            PgStore(store.conn, dimension, identity).check()
    assert not store.conn.execute("""SELECT 1 FROM pg_indexes WHERE schemaname=%s
        AND (indexdef ILIKE '%%hnsw%%' OR indexdef ILIKE '%%ivfflat%%')""", (SCHEMA,)).fetchall()


def test_search_filters_provenance_and_unchanged(db):
    store, sources = db
    note = read_note(FIXTURE, sources[0])
    assert store.index(note, MockEmbeddingProvider()) == "indexed"
    before = store.conn.execute(f"SELECT * FROM {SCHEMA}.documents WHERE doc_id=%s", (note.document.id,)).fetchone()
    provider = Mock(dimension=128)
    assert store.index(note, provider) == "unchanged"
    provider.embed_batch.assert_not_called()
    assert before == store.conn.execute(f"SELECT * FROM {SCHEMA}.documents WHERE doc_id=%s", (note.document.id,)).fetchone()
    hits = store.search(note.chunks[0].content, MockEmbeddingProvider(), 1, sources[0], ["absent", "postgres"])
    assert len(hits) == 1
    assert hits[0]["similarity"] == pytest.approx(1, abs=1e-6)
    assert hits[0]["source_path"] == sources[0]
    assert hits[0]["heading_path"] == note.chunks[0].heading
    assert hits[0]["content"] == note.chunks[0].content
    assert store.search("vectors", MockEmbeddingProvider(), source_path=sources[0], tags=["absent"]) == []
    assert store.search("vectors", MockEmbeddingProvider(), source_path=sources[1]) == []


def test_atomic_update_failure_then_replace(db, tmp_path):
    store, sources = db
    original = read_note(FIXTURE, sources[0])
    store.index(original, MockEmbeddingProvider())
    old_doc = store.conn.execute(f"SELECT * FROM {SCHEMA}.documents WHERE doc_id=%s", (original.document.id,)).fetchone()
    old_chunks = store.conn.execute(f"SELECT * FROM {SCHEMA}.chunks WHERE doc_id=%s ORDER BY chunk_index", (original.document.id,)).fetchall()
    path = tmp_path / "changed.md"
    path.write_text("---\ntitle: Revised\ntags: [changed]\n---\n# New\nCompletely replaced note content.", encoding="utf-8")
    changed = read_note(path, sources[0])
    changed.chunks[0].chunk_id = None  # NOT NULL failure after metadata update and old-chunk deletion
    with pytest.raises(psycopg.errors.NotNullViolation):
        store.index(changed, MockEmbeddingProvider())
    assert old_doc == store.conn.execute(f"SELECT * FROM {SCHEMA}.documents WHERE doc_id=%s", (original.document.id,)).fetchone()
    assert old_chunks == store.conn.execute(f"SELECT * FROM {SCHEMA}.chunks WHERE doc_id=%s ORDER BY chunk_index", (original.document.id,)).fetchall()
    changed = read_note(path, sources[0])
    assert store.index(changed, MockEmbeddingProvider()) == "updated"
    rows = store.conn.execute(f"SELECT content FROM {SCHEMA}.chunks WHERE doc_id=%s", (original.document.id,)).fetchall()
    assert [r["content"] for r in rows] == [c.content for c in changed.chunks]
    assert not {r["content"] for r in old_chunks} & {r["content"] for r in rows}
    assert store.search("replaced", MockEmbeddingProvider(), source_path=sources[0], tags=["postgres"]) == []
    assert store.search("replaced", MockEmbeddingProvider(), source_path=sources[0], tags=["changed"])


def test_delete_cascade_isolation(db):
    store, sources = db
    notes = [read_note(FIXTURE, source) for source in sources]
    for note in notes:
        store.index(note, MockEmbeddingProvider())
    assert store.delete(sources[0]) == 1
    assert store.delete(sources[0]) == 0
    assert store.conn.execute(f"SELECT count(*) AS n FROM {SCHEMA}.chunks WHERE doc_id=%s", (notes[0].document.id,)).fetchone()["n"] == 0
    assert store.conn.execute(f"SELECT count(*) AS n FROM {SCHEMA}.chunks WHERE doc_id=%s", (notes[1].document.id,)).fetchone()["n"] == len(notes[1].chunks)
