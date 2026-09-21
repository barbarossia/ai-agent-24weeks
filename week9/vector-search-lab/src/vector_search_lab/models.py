"""Data models for Vector Search Lab (Week 9)."""

from typing import Any
from pydantic import BaseModel, Field


class Document(BaseModel):
    """Raw document before chunking."""

    id: str = Field(..., description="Unique document ID (e.g. filename or slug)")
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Full text content of document")
    category: str = Field(default="general", description="Category (e.g. openwrt, esxi, docker)")
    source_file: str = Field(default="", description="Source file path")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary extra metadata")


class Chunk(BaseModel):
    """A granular chunk of a document ready for embedding and vector indexing."""

    chunk_id: str = Field(..., description="Unique ID for this chunk (e.g. doc_id#chunk_001)")
    doc_id: str = Field(..., description="Parent document ID")
    chunk_index: int = Field(..., description="0-based index of this chunk in the document")
    title: str = Field(..., description="Parent document title")
    heading: str = Field(default="", description="Section heading breadcrumb")
    content: str = Field(..., description="Text content of this chunk")
    category: str = Field(default="general", description="Category for metadata filtering")
    source_file: str = Field(default="", description="Source file path")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom metadata attributes")
    embedding: list[float] | None = Field(default=None, description="Vector representation")


class MetadataFilter(BaseModel):
    """Filtering constraints for vector retrieval."""

    category: str | None = Field(default=None, description="Exact match on category")
    source_file: str | None = Field(default=None, description="Exact match on source file")
    doc_id: str | None = Field(default=None, description="Exact match on document ID")
    min_similarity: float = Field(default=0.0, description="Minimum cosine similarity threshold [0.0, 1.0]")


class SearchResult(BaseModel):
    """A single result from vector search."""

    chunk: Chunk = Field(..., description="Retrieved chunk")
    similarity: float = Field(..., description="Cosine similarity score in range [-1.0, 1.0]")
    distance: float = Field(..., description="Cosine distance = 1.0 - similarity")
    rank: int = Field(..., description="1-based rank in result set")


class VectorStoreConfig(BaseModel):
    """Configuration for vector database backend."""

    backend: str = Field(default="memory", description="'memory' or 'pgvector'")
    dimension: int = Field(default=128, description="Embedding vector dimension")
    pg_connection_string: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/homelab_rag",
        description="PostgreSQL connection URI",
    )
    table_name: str = Field(default="homelab_document_chunks", description="Target SQL table")
    index_type: str = Field(default="hnsw", description="'hnsw' or 'ivfflat'")
