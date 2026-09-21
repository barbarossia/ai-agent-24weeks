"""End-to-End Vector Search and Ingestion Pipeline.

Combines:
1. Markdown Chunker: document -> chunks with heading context and overlap
2. Embedding Provider: chunk text -> dense float vector
3. Vector Store: index vectors + metadata -> execute top-k cosine search
"""

from pathlib import Path
from vector_search_lab.models import Document, Chunk, SearchResult, MetadataFilter
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.embeddings import BaseEmbeddingProvider, MockEmbeddingProvider
from vector_search_lab.vector_store import BaseVectorStore, InMemoryVectorStore


class VectorSearchPipeline:
    """Complete RAG vector search pipeline."""

    def __init__(
        self,
        chunker: MarkdownChunker | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
        vector_store: BaseVectorStore | None = None,
    ):
        self.chunker = chunker or MarkdownChunker()
        self.embedding_provider = embedding_provider or MockEmbeddingProvider()
        self.vector_store = vector_store or InMemoryVectorStore()
        self._doc_count = 0

    @property
    def doc_count(self) -> int:
        return self._doc_count

    @property
    def chunk_count(self) -> int:
        return self.vector_store.count()

    def ingest_documents(self, docs: list[Document]) -> int:
        """Process documents through chunker, embedder, and vector store."""
        total_added = 0
        all_chunks: list[Chunk] = []

        for doc in docs:
            chunks = self.chunker.chunk_document(doc)
            for chunk in chunks:
                # Context-enriched embedding: prepend heading breadcrumb if present
                text_to_embed = f"{chunk.heading}\n{chunk.content}" if chunk.heading else chunk.content
                chunk.embedding = self.embedding_provider.embed_text(text_to_embed)
                all_chunks.append(chunk)
            self._doc_count += 1

        if all_chunks:
            total_added = self.vector_store.add(all_chunks)

        return total_added

    def ingest_file(self, file_path: str | Path, category: str = "general") -> int:
        """Read a single markdown or text file and ingest into vector store."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        content = path.read_text(encoding="utf-8")
        title = path.stem.replace("_", " ").title()

        doc = Document(
            id=path.name,
            title=title,
            content=content,
            category=category,
            source_file=str(path),
        )
        return self.ingest_documents([doc])

    def ingest_directory(self, dir_path: str | Path, glob_pattern: str = "*.md") -> int:
        """Scan a directory and ingest all matching documentation files."""
        folder = Path(dir_path)
        if not folder.is_dir():
            raise NotADirectoryError(f"Directory not found: {folder}")

        files = sorted(folder.glob(glob_pattern))
        docs: list[Document] = []

        for path in files:
            content = path.read_text(encoding="utf-8")
            title = path.stem.replace("_", " ").title()

            # Infer category from filename
            lower_name = path.name.lower()
            if "openwrt" in lower_name:
                category = "openwrt"
            elif "esxi" in lower_name:
                category = "esxi"
            elif "docker" in lower_name:
                category = "docker"
            else:
                category = "general"

            docs.append(
                Document(
                    id=path.name,
                    title=title,
                    content=content,
                    category=category,
                    source_file=path.name,
                )
            )

        return self.ingest_documents(docs)

    def search(
        self,
        query: str,
        top_k: int = 3,
        category: str | None = None,
        min_similarity: float = 0.0,
    ) -> list[SearchResult]:
        """Perform semantic vector search for a text query."""
        if not query or not query.strip():
            return []

        query_vector = self.embedding_provider.embed_text(query)
        metadata_filter = (
            MetadataFilter(category=category, min_similarity=min_similarity)
            if (category or min_similarity > 0.0)
            else None
        )

        return self.vector_store.search(
            query_vector=query_vector,
            top_k=top_k,
            filter=metadata_filter,
        )
