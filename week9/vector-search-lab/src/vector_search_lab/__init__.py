"""Week 9 — Embedding and Vector Search Lab."""

from vector_search_lab.models import (
    Document,
    Chunk,
    SearchResult,
    MetadataFilter,
    VectorStoreConfig,
)
from vector_search_lab.math_utils import (
    cosine_similarity,
    cosine_distance,
    euclidean_distance,
    dot_product,
    normalize_vector,
)
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.embeddings import (
    BaseEmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from vector_search_lab.vector_store import (
    BaseVectorStore,
    InMemoryVectorStore,
    PgVectorStore,
)
from vector_search_lab.pipeline import VectorSearchPipeline

__all__ = [
    "Document",
    "Chunk",
    "SearchResult",
    "MetadataFilter",
    "VectorStoreConfig",
    "cosine_similarity",
    "cosine_distance",
    "euclidean_distance",
    "dot_product",
    "normalize_vector",
    "MarkdownChunker",
    "BaseEmbeddingProvider",
    "MockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "BaseVectorStore",
    "InMemoryVectorStore",
    "PgVectorStore",
    "VectorSearchPipeline",
]
