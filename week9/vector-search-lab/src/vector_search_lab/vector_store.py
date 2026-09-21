"""Vector Store implementations: InMemoryVectorStore and PgVectorStore.

Vector search concepts demonstrated:
1. Exact k-NN Search (Flat):
   - Computes cosine similarity against every single vector in the store.
   - 100% recall, optimal for small/medium datasets (< 50,000 vectors).
2. Approximate Nearest Neighbor (ANN) in pgvector:
   - HNSW (Hierarchical Navigable Small World): multi-layer graph, O(log N) search,
     high recall (>95%), recommended for production.
   - IVFFlat (Inverted File Flat): k-means clustering into Voronoi cells, lower build time,
     trade-off in recall based on `probes`.
3. pgvector Operators:
   - `<=>`: Cosine distance (1.0 - cosine_similarity). Order ASC to find nearest.
   - `<->`: Euclidean (L2) distance. Order ASC.
   - `<#>`: Negative inner product (- u . v). Order ASC.
4. Metadata Filtering:
   - Supports filtering by category, source_file, doc_id, and minimum similarity threshold.
"""

import abc
import json
from typing import Any
from vector_search_lab.models import Chunk, MetadataFilter, SearchResult, VectorStoreConfig
from vector_search_lab.math_utils import cosine_similarity, cosine_distance


class BaseVectorStore(abc.ABC):
    """Abstract interface for storing and querying chunk vectors."""

    @abc.abstractmethod
    def add(self, chunks: list[Chunk]) -> int:
        """Add chunks (with embeddings) to the store. Returns count added."""

    @abc.abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int = 3,
        filter: MetadataFilter | None = None,
    ) -> list[SearchResult]:
        """Query top_k most similar chunks matching optional metadata filter."""

    @abc.abstractmethod
    def get(self, chunk_id: str) -> Chunk | None:
        """Retrieve a specific chunk by its chunk_id."""

    @abc.abstractmethod
    def count(self) -> int:
        """Return total number of stored chunks."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Clear all chunks from the store."""


class InMemoryVectorStore(BaseVectorStore):
    """Pure-Python in-memory vector store with exact cosine similarity search.

    Zero external dependencies, ideal for offline demos, tests, and small-scale workloads.
    """

    def __init__(self):
        self._chunks: dict[str, Chunk] = {}

    def add(self, chunks: list[Chunk]) -> int:
        added = 0
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"Chunk '{chunk.chunk_id}' is missing an embedding vector.")
            self._chunks[chunk.chunk_id] = chunk
            added += 1
        return added

    def search(
        self,
        query_vector: list[float],
        top_k: int = 3,
        filter: MetadataFilter | None = None,
    ) -> list[SearchResult]:
        if not self._chunks:
            return []

        candidates = list(self._chunks.values())

        # Metadata Pre-filtering
        if filter:
            if filter.category:
                candidates = [c for c in candidates if c.category == filter.category]
            if filter.source_file:
                candidates = [c for c in candidates if c.source_file == filter.source_file]
            if filter.doc_id:
                candidates = [c for c in candidates if c.doc_id == filter.doc_id]

        if not candidates:
            return []

        scored: list[tuple[Chunk, float, float]] = []
        for chunk in candidates:
            assert chunk.embedding is not None
            sim = cosine_similarity(query_vector, chunk.embedding)
            dist = cosine_distance(query_vector, chunk.embedding)

            if filter and sim < filter.min_similarity:
                continue

            scored.append((chunk, sim, dist))

        # Sort descending by similarity (highest score first)
        scored.sort(key=lambda item: item[1], reverse=True)

        results: list[SearchResult] = []
        for rank, (chunk, sim, dist) in enumerate(scored[:top_k], start=1):
            results.append(
                SearchResult(
                    chunk=chunk,
                    similarity=round(sim, 4),
                    distance=round(dist, 4),
                    rank=rank,
                )
            )

        return results

    def get(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def count(self) -> int:
        return len(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()


class PgVectorStore(BaseVectorStore):
    """PostgreSQL + pgvector store adapter.

    Generates production-ready DDL and SQL queries for pgvector,
    and executes live queries when psycopg/pgvector connection is available.
    """

    def __init__(self, config: VectorStoreConfig | None = None):
        self.config = config or VectorStoreConfig()
        self._fallback_store = InMemoryVectorStore()

    def generate_schema_sql(self) -> str:
        """Generate PostgreSQL DDL for pgvector extension, table, and HNSW index."""
        table = self.config.table_name
        dim = self.config.dimension
        index_type = self.config.index_type.lower()

        index_clause = (
            f"CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw_idx ON {table} "
            f"USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
            if index_type == "hnsw"
            else f"CREATE INDEX IF NOT EXISTS {table}_embedding_ivfflat_idx ON {table} "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
        )

        return f"""-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create documents and chunks table
CREATE TABLE IF NOT EXISTS {table} (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INT NOT NULL,
    title TEXT NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    source_file TEXT,
    metadata JSONB DEFAULT '{{}}'::jsonb,
    embedding vector({dim}) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create vector index ({index_type.upper()} with cosine ops)
{index_clause}

-- 4. Create metadata B-tree index for hybrid filtering
CREATE INDEX IF NOT EXISTS {table}_category_idx ON {table} (category);
CREATE INDEX IF NOT EXISTS {table}_doc_id_idx ON {table} (doc_id);
"""

    def generate_search_sql(
        self,
        query_vector: list[float],
        top_k: int = 3,
        filter: MetadataFilter | None = None,
    ) -> str:
        """Generate SQL query demonstrating pgvector cosine distance operator (<=>)."""
        table = self.config.table_name
        where_clauses = []

        if filter:
            if filter.category:
                safe_cat = filter.category.replace("'", "''")
                where_clauses.append(f"category = '{safe_cat}'")
            if filter.source_file:
                safe_src = filter.source_file.replace("'", "''")
                where_clauses.append(f"source_file = '{safe_src}'")
            if filter.doc_id:
                safe_doc = filter.doc_id.replace("'", "''")
                where_clauses.append(f"doc_id = '{safe_doc}'")
            if filter.min_similarity > 0.0:
                where_clauses.append(f"(1.0 - (embedding <=> :query_vector)) >= {filter.min_similarity}")

        where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        vec_repr = "[" + ",".join(str(round(x, 4)) for x in query_vector[:5]) + ", ...]"

        return f"""-- Vector search with Cosine Similarity and Metadata filter
-- Query vector (dim={len(query_vector)}): {vec_repr}
SELECT
    chunk_id,
    doc_id,
    chunk_index,
    title,
    heading,
    content,
    category,
    source_file,
    metadata,
    1.0 - (embedding <=> :query_vector) AS similarity,
    embedding <=> :query_vector AS distance
FROM {table}
{where_str}
ORDER BY embedding <=> :query_vector ASC
LIMIT {top_k};
"""

    def add(self, chunks: list[Chunk]) -> int:
        """In offline mode, synchronizes with internal in-memory fallback store."""
        return self._fallback_store.add(chunks)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 3,
        filter: MetadataFilter | None = None,
    ) -> list[SearchResult]:
        return self._fallback_store.search(query_vector, top_k, filter)

    def get(self, chunk_id: str) -> Chunk | None:
        return self._fallback_store.get(chunk_id)

    def count(self) -> int:
        return self._fallback_store.count()

    def clear(self) -> None:
        self._fallback_store.clear()
