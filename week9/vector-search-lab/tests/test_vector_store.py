"""Tests for Vector Store implementations (InMemoryVectorStore and PgVectorStore)."""

import pytest
from vector_search_lab.models import Chunk, MetadataFilter, VectorStoreConfig
from vector_search_lab.vector_store import InMemoryVectorStore, PgVectorStore


def test_in_memory_vector_store_add_and_count():
    store = InMemoryVectorStore()
    assert store.count() == 0

    chunk = Chunk(
        chunk_id="doc1#001",
        doc_id="doc1",
        chunk_index=0,
        title="Doc 1",
        content="Sample content",
        category="network",
        embedding=[1.0, 0.0, 0.0],
    )
    store.add([chunk])
    assert store.count() == 1
    assert store.get("doc1#001") == chunk


def test_missing_embedding_raises_value_error():
    store = InMemoryVectorStore()
    chunk = Chunk(
        chunk_id="bad#001",
        doc_id="bad",
        chunk_index=0,
        title="Bad",
        content="No vector",
        embedding=None,
    )
    with pytest.raises(ValueError, match="missing an embedding vector"):
        store.add([chunk])


def test_top_k_search_ranks_correctly():
    store = InMemoryVectorStore()
    # Three chunks with different angles to [1, 0, 0]
    c1 = Chunk(
        chunk_id="c1",
        doc_id="d1",
        chunk_index=0,
        title="C1",
        content="Aligned",
        embedding=[1.0, 0.0, 0.0],  # sim = 1.0
    )
    c2 = Chunk(
        chunk_id="c2",
        doc_id="d2",
        chunk_index=0,
        title="C2",
        content="Diagonal",
        embedding=[0.7071, 0.7071, 0.0],  # sim ~ 0.707
    )
    c3 = Chunk(
        chunk_id="c3",
        doc_id="d3",
        chunk_index=0,
        title="C3",
        content="Orthogonal",
        embedding=[0.0, 1.0, 0.0],  # sim = 0.0
    )
    store.add([c1, c2, c3])

    query = [1.0, 0.0, 0.0]
    results = store.search(query, top_k=2)

    assert len(results) == 2
    assert results[0].chunk.chunk_id == "c1"
    assert results[0].rank == 1
    assert results[0].similarity == 1.0
    assert results[1].chunk.chunk_id == "c2"
    assert results[1].rank == 2


def test_metadata_filtering():
    store = InMemoryVectorStore()
    c_openwrt = Chunk(
        chunk_id="owrt",
        doc_id="d1",
        chunk_index=0,
        title="OpenWrt",
        content="Ubus",
        category="openwrt",
        embedding=[1.0, 0.0, 0.0],
    )
    c_docker = Chunk(
        chunk_id="dock",
        doc_id="d2",
        chunk_index=0,
        title="Docker",
        content="Compose",
        category="docker",
        embedding=[1.0, 0.0, 0.0],
    )
    store.add([c_openwrt, c_docker])

    query = [1.0, 0.0, 0.0]
    # Filter by docker
    res_docker = store.search(query, top_k=5, filter=MetadataFilter(category="docker"))
    assert len(res_docker) == 1
    assert res_docker[0].chunk.chunk_id == "dock"

    # Filter by openwrt
    res_owrt = store.search(query, top_k=5, filter=MetadataFilter(category="openwrt"))
    assert len(res_owrt) == 1
    assert res_owrt[0].chunk.chunk_id == "owrt"


def test_min_similarity_filter():
    store = InMemoryVectorStore()
    c1 = Chunk(
        chunk_id="c1",
        doc_id="d1",
        chunk_index=0,
        title="C1",
        content="High match",
        embedding=[1.0, 0.0, 0.0],
    )
    c2 = Chunk(
        chunk_id="c2",
        doc_id="d2",
        chunk_index=0,
        title="C2",
        content="Low match",
        embedding=[0.0, 1.0, 0.0],
    )
    store.add([c1, c2])

    query = [1.0, 0.0, 0.0]
    results = store.search(query, top_k=5, filter=MetadataFilter(min_similarity=0.5))
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c1"


def test_pgvector_sql_generation():
    cfg = VectorStoreConfig(
        backend="pgvector",
        dimension=128,
        table_name="test_homelab_chunks",
        index_type="hnsw",
    )
    pg = PgVectorStore(cfg)
    schema_sql = pg.generate_schema_sql()

    assert "CREATE EXTENSION IF NOT EXISTS vector;" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS test_homelab_chunks" in schema_sql
    assert "vector(128) NOT NULL" in schema_sql
    assert "USING hnsw (embedding vector_cosine_ops)" in schema_sql

    query_sql = pg.generate_search_sql(
        query_vector=[0.1, 0.2, 0.3],
        top_k=5,
        filter=MetadataFilter(category="openwrt"),
    )
    assert "<=> :query_vector" in query_sql
    assert "category = 'openwrt'" in query_sql
    assert "LIMIT 5" in query_sql
