"""Vector adapter tests: Week 9 reuse without Week 9 modification.

These verify the properties the runbook requires: Week 9 public APIs are used as a
black box, the dense baseline is the offline ``MockEmbeddingProvider``, the ranking
is deterministic with an explicit ``chunk_id`` tie-break, and the Week 10 chunk view
provably matches the Week 9 vector index.
"""

from __future__ import annotations

import pytest
from vector_search_lab import (
    Document,
    MarkdownChunker,
    MockEmbeddingProvider,
    VectorSearchPipeline,
)

from production_rag_lab.retrieval import (
    EMBEDDING_DIMENSION,
    VectorAdapter,
    load_corpus_documents,
)

from conftest import make_chunk

SAMPLE = """# Sample

Alpha and beta content for the offline baseline.

## Second

Gamma delta epsilon.
"""


@pytest.fixture()
def tiny_corpus(tmp_path):
    """A one-file corpus with a single heading section (one chunk)."""
    (tmp_path / "sample_doc.md").write_text(SAMPLE, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------- Week 9 reuse


def test_uses_week9_offline_mock_provider(tiny_corpus) -> None:
    adapter = VectorAdapter.from_data_dir(tiny_corpus)
    assert adapter.provider_name == "MockEmbeddingProvider"
    assert isinstance(adapter.pipeline.embedding_provider, MockEmbeddingProvider)
    assert adapter.dimension == EMBEDDING_DIMENSION


def test_no_network_client_is_imported(tiny_corpus) -> None:
    """The offline provider must not pull in an HTTP stack."""
    import sys

    VectorAdapter.from_data_dir(tiny_corpus)
    assert "httpx" not in sys.modules


def test_chunk_view_matches_week9_index(tiny_corpus) -> None:
    adapter = VectorAdapter.from_data_dir(tiny_corpus)
    assert adapter.chunk_count == len(adapter.chunks())
    assert adapter.chunk_count == adapter.pipeline.chunk_count
    for chunk in adapter.chunks():
        assert adapter.pipeline.vector_store.get(chunk.chunk_id) is not None


def test_consistency_guard_rejects_a_chunk_absent_from_the_index(tiny_corpus) -> None:
    pipeline = VectorSearchPipeline(
        chunker=MarkdownChunker(), embedding_provider=MockEmbeddingProvider()
    )
    pipeline.ingest_documents(
        [Document(id="a.md", title="A", content=SAMPLE, source_file="a.md")]
    )
    with pytest.raises(RuntimeError, match="absent from the Week 9 vector index"):
        VectorAdapter(pipeline, [make_chunk("ghost#chunk_000", "ghost.md", "x")])


def test_consistency_guard_rejects_a_chunk_count_mismatch() -> None:
    pipeline = VectorSearchPipeline(
        chunker=MarkdownChunker(), embedding_provider=MockEmbeddingProvider()
    )
    pipeline.ingest_documents(
        [Document(id="a.md", title="A", content=SAMPLE, source_file="a.md")]
    )
    # The pipeline indexed one chunk; claiming two must be rejected up front.
    with pytest.raises(RuntimeError, match="disagree"):
        VectorAdapter(
            pipeline,
            [
                make_chunk("a.md#chunk_000", "a.md", "one"),
                make_chunk("a.md#chunk_001", "a.md", "two"),
            ],
        )


def test_missing_data_dir_raises(tmp_path) -> None:
    with pytest.raises(NotADirectoryError):
        load_corpus_documents(tmp_path / "nope")


def test_document_ids_are_source_file_names(tiny_corpus) -> None:
    documents = load_corpus_documents(tiny_corpus)
    assert [doc.id for doc in documents] == ["sample_doc.md"]
    assert documents[0].source_file == "sample_doc.md"
    assert documents[0].title == "Sample Doc"


def test_documents_are_loaded_in_sorted_filename_order(tmp_path) -> None:
    for name in ("c_third.md", "a_first.md", "b_second.md"):
        (tmp_path / name).write_text(SAMPLE, encoding="utf-8")
    assert [doc.id for doc in load_corpus_documents(tmp_path)] == [
        "a_first.md",
        "b_second.md",
        "c_third.md",
    ]


def test_week9_corpus_shape(retriever) -> None:
    """The shared Week 9 corpus: 4 documents, 17 chunks, unchanged by Week 10."""
    assert retriever.doc_count == 4
    assert retriever.chunk_count == 17
    assert retriever.vector_provider == "MockEmbeddingProvider"
    assert retriever.document_ids == (
        "docker_homelab_services.md",
        "esxi_storage_management.md",
        "openwrt_firewall_setup.md",
        "openwrt_ubus_guide.md",
    )


# ----------------------------------------------------------------- ranking


def test_ranking_is_sorted_by_similarity_then_chunk_id(retriever) -> None:
    hits = retriever._vector.rank("OpenWrt 端口转发 DNAT")  # noqa: SLF001 - adapter unit
    assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))
    for previous, current in zip(hits, hits[1:]):
        if previous.similarity == current.similarity:
            assert previous.chunk_id < current.chunk_id
        else:
            assert previous.similarity > current.similarity


def test_ranking_is_deterministic(retriever) -> None:
    query = "ubus session login"
    first = retriever._vector.rank(query)  # noqa: SLF001
    second = retriever._vector.rank(query)  # noqa: SLF001
    assert [(h.chunk_id, h.similarity) for h in first] == [
        (h.chunk_id, h.similarity) for h in second
    ]


def test_empty_query_returns_no_results(tiny_corpus) -> None:
    adapter = VectorAdapter.from_data_dir(tiny_corpus)
    for query in ("", "   ", "\n"):
        assert adapter.rank(query) == []


def test_ranking_covers_every_chunk(retriever) -> None:
    hits = retriever._vector.rank("docker stats")  # noqa: SLF001
    assert len(hits) == retriever.chunk_count
    assert len({hit.chunk_id for hit in hits}) == retriever.chunk_count
    assert {hit.doc_id for hit in hits} == set(retriever.document_ids)


def test_identical_queries_produce_identical_top_hit(retriever) -> None:
    query = "esxcli storage filesystem list"
    first = retriever._vector.rank(query)  # noqa: SLF001
    second = retriever._vector.rank(query)  # noqa: SLF001
    assert first[0].chunk_id == second[0].chunk_id
    assert first[0].similarity == second[0].similarity


def test_no_similarity_filtering_is_applied(retriever) -> None:
    """The dense baseline returns its whole ranking, including low similarities."""
    hits = retriever._vector.rank("完全无关的查询文本 zzzz")  # noqa: SLF001
    assert len(hits) == retriever.chunk_count
