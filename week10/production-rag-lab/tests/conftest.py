"""Shared offline test fixtures.

Every test here runs locally with no network, no API key, and no database. The
end-to-end fixtures use the real read-only Week 9 corpus so the tests exercise the
same data the CLI uses.
"""

from __future__ import annotations

import pytest
from vector_search_lab import Chunk

from production_rag_lab.paths import get_default_data_dir
from production_rag_lab.retrieval import ProductionRagRetriever


def make_chunk(
    chunk_id: str,
    doc_id: str,
    content: str,
    *,
    title: str = "",
    heading: str = "",
) -> Chunk:
    """Build a minimal Week 9 ``Chunk`` for hand-controlled unit fixtures."""
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        chunk_index=0,
        title=title,
        heading=heading,
        content=content,
        source_file=doc_id,
    )


@pytest.fixture(scope="session")
def corpus_dir():
    """The read-only Week 9 corpus directory used by every method."""
    return get_default_data_dir()


@pytest.fixture(scope="session")
def retriever(corpus_dir) -> ProductionRagRetriever:
    """A session-wide retriever over the real Week 9 corpus (17 chunks)."""
    return ProductionRagRetriever(corpus_dir)


@pytest.fixture(scope="session")
def queries_path():
    """The bundled fixed 24-row gold-labeled query set."""
    from production_rag_lab.paths import get_default_queries_path

    return get_default_queries_path()
