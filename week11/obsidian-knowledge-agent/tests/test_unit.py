from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from vector_search_lab.embeddings import MockEmbeddingProvider

from obsidian_knowledge_agent.cli import main, parser
from obsidian_knowledge_agent.config import provider_from_env
from obsidian_knowledge_agent.ingestion import document_id, read_note
from obsidian_knowledge_agent.store import PgStore, search_filters, vector_literal

FIXTURE = Path(__file__).parent / "fixtures/note.md"


def test_metadata_and_chunk_reuse():
    note = read_note(FIXTURE, "integration-test/unit/note.md")
    assert note.document.title == "Vector field notes"
    assert note.tags == ["postgres", "retrieval"]
    assert not note.document.content.startswith("---")
    assert note.modified_at.tzinfo is not None
    assert note.chunks[0].heading == "Vector field notes > PostgreSQL > Cosine retrieval"
    assert note.chunks[0].metadata["tags"] == note.tags
    assert note.chunks[0].source_file == note.document.source_file
    assert note.chunks[0].chunk_id == note.document.id + "#chunk_000"


def test_identity_and_hash(tmp_path):
    path = tmp_path / "note.md"
    path.write_bytes(FIXTURE.read_bytes())
    first = read_note(path)
    assert first == read_note(path)
    path.write_text("# Changed\nnew content", encoding="utf-8")
    second = read_note(path)
    assert first.document.id == second.document.id
    assert first.chunks[0].chunk_id == second.chunks[0].chunk_id
    assert first.content_hash != second.content_hash
    assert document_id("a") != document_id("b")


@pytest.mark.parametrize("text,title,tags", [
    ("# Heading\nbody", "Heading", []), ("body", "note", []),
    ("---\ntitle: Named\ntags: '#one, two one'\n---\nbody", "Named", ["one", "two"]),
])
def test_metadata_variants(tmp_path, text, title, tags):
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    note = read_note(path)
    assert (note.document.title, note.tags) == (title, tags)


@pytest.mark.parametrize("text", ["---\n[one]\n---\nbody", "---\ntags: [1]\n---\nbody", "---\nunclosed"])
def test_invalid_frontmatter(tmp_path, text):
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        read_note(path)


def test_no_directory_scan(tmp_path):
    with pytest.raises(ValueError):
        read_note(tmp_path)
    with pytest.raises(ValueError):
        read_note(FIXTURE, " ")


def test_filter_parameters():
    where, params = search_filters("x' OR true --", ["one", "two"])
    assert where == " WHERE d.source_path = %s AND d.tags && %s::text[]"
    assert params == ["x' OR true --", ["one", "two"]]
    assert search_filters() == ("", [])


@pytest.mark.parametrize("vector,dimension", [([1], 2), ([float("nan")], 1), ([float("inf")], 1), ([0, 0], 2)])
def test_reject_bad_vectors(vector, dimension):
    with pytest.raises(ValueError):
        vector_literal(vector, dimension)


def test_provider_config(monkeypatch):
    monkeypatch.setenv("W11_PROVIDER", "mock")
    monkeypatch.setenv("W11_DIMENSION", "128")
    provider, identity = provider_from_env()
    assert provider.dimension == 128 and identity == "mock:128:week9-v1"
    monkeypatch.setenv("W11_PROVIDER", "invalid")
    with pytest.raises(ValueError):
        provider_from_env()


def test_cli_shape():
    for command in ["init", "check"]:
        assert parser().parse_args([command]).command == command
    args = parser().parse_args(["search", "query", "--top-k", "2", "--tag", "one", "--tag", "two", "--source-path", "a"])
    assert (args.top_k, args.tag, args.source_path) == (2, ["one", "two"], "a")
    assert parser().parse_args(["delete", "a"]).source_path == "a"
    with pytest.raises(SystemExit):
        parser().parse_args(["index"])


def test_cli_redacts_errors(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("secret credential")
    monkeypatch.setattr(PgStore, "connect", fail)
    assert main(["check"]) == 1
    assert "secret credential" not in capsys.readouterr().err


class TransactionConnection:
    """Minimal transaction fault harness; SQL behavior is verified separately on PostgreSQL."""
    def __init__(self, content_hash=None):
        self.content_hash = content_hash
        self.writes = []
        self.fail_insert = False

    @contextmanager
    def transaction(self):
        before = deepcopy(self.writes)
        try:
            yield
        except Exception:
            self.writes = before
            raise

    def execute(self, sql, params=()):
        if "SELECT content_hash" in sql:
            return Mock(fetchone=lambda: {"content_hash": self.content_hash} if self.content_hash else None)
        if sql.lstrip().startswith(("INSERT", "DELETE")):
            if self.fail_insert and "INSERT INTO week11_obsidian_agent.chunks" in sql:
                raise RuntimeError("injected write failure")
            self.writes.append((sql, params))
        return Mock(rowcount=1)


def offline_store(conn):
    store = PgStore(conn)
    store.check = Mock()
    return store


def test_unchanged_skips_embeddings_and_writes():
    note = read_note(FIXTURE)
    conn = TransactionConnection(note.content_hash)
    provider = Mock(dimension=128)
    assert offline_store(conn).index(note, provider) == "unchanged"
    provider.embed_batch.assert_not_called()
    assert conn.writes == []


def test_changed_replacement_and_rollback():
    note = read_note(FIXTURE)
    conn = TransactionConnection("old-hash")
    store = offline_store(conn)
    assert store.index(note, MockEmbeddingProvider()) == "updated"
    assert "DELETE FROM week11_obsidian_agent.chunks WHERE doc_id=%s" == conn.writes[1][0]
    assert len(conn.writes) == 2 + len(note.chunks)
    before = deepcopy(conn.writes)
    conn.fail_insert = True
    with pytest.raises(RuntimeError):
        store.index(note, MockEmbeddingProvider())
    assert conn.writes == before


def test_delete_uses_exact_document_and_database_cascade():
    conn = TransactionConnection()
    assert offline_store(conn).delete("integration-test/unit/note.md") == 1
    assert len(conn.writes) == 1
    sql, params = conn.writes[0]
    assert sql == "DELETE FROM week11_obsidian_agent.documents WHERE source_path=%s"
    assert params == ("integration-test/unit/note.md",)
