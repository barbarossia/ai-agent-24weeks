"""Tests for embedding providers."""

import math
import pytest
from vector_search_lab.embeddings import MockEmbeddingProvider
from vector_search_lab.math_utils import cosine_similarity, vector_norm


def test_mock_embedder_dimension():
    embedder = MockEmbeddingProvider(dimension=64)
    assert embedder.dimension == 64
    vec = embedder.embed_text("OpenWrt ubus protocol")
    assert len(vec) == 64


def test_invalid_dimension_raises():
    with pytest.raises(ValueError, match="dimension must be positive"):
        MockEmbeddingProvider(dimension=0)


def test_output_vector_is_unit_normalized():
    embedder = MockEmbeddingProvider(dimension=128)
    vec = embedder.embed_text("ESXi storage filesystem troubleshooting")
    norm = vector_norm(vec)
    assert math.isclose(norm, 1.0, abs_tol=1e-5)


def test_deterministic_embedding():
    embedder = MockEmbeddingProvider(dimension=128)
    text = "Docker container healthcheck configuration"
    vec1 = embedder.embed_text(text)
    vec2 = embedder.embed_text(text)
    assert vec1 == vec2
    assert math.isclose(cosine_similarity(vec1, vec2), 1.0, abs_tol=1e-6)


def test_related_texts_have_higher_similarity_than_unrelated():
    embedder = MockEmbeddingProvider(dimension=128)
    q = "OpenWrt 路由器网络接口配置与流量"
    doc_related = "OpenWrt network.interface.dump 查询所有网络接口与网关状态"
    doc_unrelated = "西红柿炒鸡蛋烹饪食谱制作步骤"

    v_q = embedder.embed_text(q)
    v_rel = embedder.embed_text(doc_related)
    v_unrel = embedder.embed_text(doc_unrelated)

    sim_rel = cosine_similarity(v_q, v_rel)
    sim_unrel = cosine_similarity(v_q, v_unrel)

    assert sim_rel > sim_unrel


def test_empty_text_returns_zero_vector():
    embedder = MockEmbeddingProvider(dimension=32)
    vec = embedder.embed_text("")
    assert vec == [0.0] * 32
