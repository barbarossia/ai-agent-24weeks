"""Integration tests for the end-to-end Vector Search Pipeline."""

from pathlib import Path
from vector_search_lab.pipeline import VectorSearchPipeline
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.embeddings import MockEmbeddingProvider
from vector_search_lab.vector_store import InMemoryVectorStore


def test_pipeline_end_to_end_ingestion_and_search():
    chunker = MarkdownChunker(chunk_size=300, chunk_overlap=50)
    embedder = MockEmbeddingProvider(dimension=128)
    store = InMemoryVectorStore()
    pipeline = VectorSearchPipeline(chunker=chunker, embedding_provider=embedder, vector_store=store)

    data_dir = Path(__file__).resolve().parent.parent / "data"
    added = pipeline.ingest_directory(data_dir)

    assert added > 0
    assert pipeline.doc_count >= 4
    assert pipeline.chunk_count == added

    # 1. Search for OpenWrt ubus
    results_ubus = pipeline.search("OpenWrt ubus session login 接口调用", top_k=3)
    assert len(results_ubus) > 0
    top_hit = results_ubus[0]
    assert "openwrt" in top_hit.chunk.category
    assert top_hit.chunk.doc_id == "openwrt_ubus_guide.md"
    assert "ubus" in (top_hit.chunk.heading + " " + top_hit.chunk.content).lower()

    # 2. Search for Docker compose healthcheck
    results_docker = pipeline.search("Docker 容器健康检查 healthcheck", top_k=3, category="docker")
    assert len(results_docker) > 0
    for r in results_docker:
        assert r.chunk.category == "docker"
    assert "docker" in (results_docker[0].chunk.heading + " " + results_docker[0].chunk.content).lower()

    # 3. Search for ESXi datastore snapshot
    results_esxi = pipeline.search("ESXi 存储空间不足快照清理", top_k=2)
    assert len(results_esxi) > 0
    assert "esxi" in results_esxi[0].chunk.category
    assert any(word in results_esxi[0].chunk.content for word in ["快照", "存储", "VMFS"])


def test_pipeline_empty_query():
    pipeline = VectorSearchPipeline()
    assert pipeline.search("") == []
    assert pipeline.search("   ") == []
