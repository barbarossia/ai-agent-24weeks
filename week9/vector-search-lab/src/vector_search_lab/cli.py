"""Command Line Interface for Vector Search Lab (Week 9)."""

import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from vector_search_lab.pipeline import VectorSearchPipeline
from vector_search_lab.chunker import MarkdownChunker
from vector_search_lab.embeddings import MockEmbeddingProvider
from vector_search_lab.vector_store import InMemoryVectorStore, PgVectorStore
from vector_search_lab.math_utils import cosine_similarity, cosine_distance, euclidean_distance, dot_product


def get_default_data_dir() -> Path:
    """Find data directory relative to package root."""
    candidate = Path(__file__).resolve().parent.parent.parent / "data"
    if candidate.is_dir():
        return candidate
    return Path("data")


def run_demo(data_dir: Path | None = None) -> None:
    """Run an end-to-end demonstration of the vector search pipeline."""
    target_data_dir = data_dir or get_default_data_dir()

    print("=" * 72)
    print(" Week 9 — Embedding + Vector Search Lab (End-to-End Demo)")
    print("=" * 72)
    print()

    # 1. Pipeline initialization
    chunker = MarkdownChunker(chunk_size=350, chunk_overlap=70)
    embedder = MockEmbeddingProvider(dimension=128)
    store = InMemoryVectorStore()
    pipeline = VectorSearchPipeline(chunker=chunker, embedding_provider=embedder, vector_store=store)

    print(f"[*] Ingesting documents from: {target_data_dir.resolve()}")
    if not target_data_dir.exists():
        print(f"[!] Error: Data directory not found at {target_data_dir}")
        return

    num_chunks = pipeline.ingest_directory(target_data_dir)
    print(f"[+] Loaded {pipeline.doc_count} documents into {num_chunks} chunks.")
    print(f"[+] Embedding dimension: {embedder.dimension} (L2-normalized unit vectors)")
    print()

    # Display sample chunk
    sample_chunk = store.get("openwrt_ubus_guide.md#chunk_001")
    if sample_chunk:
        print("-" * 72)
        print("SAMPLE CHUNK DETAILS:")
        print(f"  Chunk ID  : {sample_chunk.chunk_id}")
        print(f"  Document  : {sample_chunk.title} ({sample_chunk.source_file})")
        print(f"  Category  : {sample_chunk.category}")
        print(f"  Heading   : {sample_chunk.heading}")
        print(f"  Length    : {len(sample_chunk.content)} chars")
        print(f"  Content   : {sample_chunk.content[:120]}...")
        print("-" * 72)
        print()

    # 2. Run Sample Queries
    test_queries = [
        ("OpenWrt 如何通过 ubus-over-HTTP 查询网络接口与设备状态？", None),
        ("防火墙如何配置端口转发 DNAT 映射到内网服务器？", None),
        ("虚拟机存储空间告警与快照膨胀处理方法？", None),
        ("Docker 容器健康检查与网络隔离配置？", "docker"),
    ]

    print("=" * 72)
    print(" EXECUTING VECTOR SEARCH QUERIES")
    print("=" * 72)
    print()

    for idx, (query_text, category_filter) in enumerate(test_queries, start=1):
        filter_str = f" [Category Filter: {category_filter}]" if category_filter else " [No Filter]"
        print(f"Query {idx}: \"{query_text}\"{filter_str}")
        results = pipeline.search(query_text, top_k=2, category=category_filter)

        if not results:
            print("  No matching chunks found.")
        for r in results:
            print(f"  Rank #{r.rank} | Similarity: {r.similarity:.4f} (Distance: {r.distance:.4f})")
            print(f"    Source : {r.chunk.source_file} > {r.chunk.heading}")
            print(f"    Snippet: {r.chunk.content[:150].strip()}...")
        print()

    # 3. Demonstrate Metadata Filter Impact
    print("=" * 72)
    print(" METADATA FILTERING COMPARISON")
    print("=" * 72)
    filter_test_query = "网络接口与配置"
    print(f"Query: \"{filter_test_query}\"")
    print()
    print("-> Without filter (All categories):")
    for r in pipeline.search(filter_test_query, top_k=2):
        print(f"   [{r.chunk.category}] {r.chunk.title} (sim: {r.similarity:.4f})")

    print("\n-> With category filter = 'docker':")
    for r in pipeline.search(filter_test_query, top_k=2, category="docker"):
        print(f"   [{r.chunk.category}] {r.chunk.title} (sim: {r.similarity:.4f})")
    print()

    # 4. PostgreSQL + pgvector DDL Preview
    print("=" * 72)
    print(" POSTGRESQL + PGVECTOR INTEGRATION PREVIEW")
    print("=" * 72)
    pg_store = PgVectorStore()
    schema_sql = pg_store.generate_schema_sql()
    print("Generated PostgreSQL Schema (HNSW + Cosine Ops):")
    for line in schema_sql.strip().split("\n")[:18]:
        print(f"  {line}")
    print("  ... (truncated)")
    print()

    sample_search_sql = pg_store.generate_search_sql(
        query_vector=[0.1234, -0.5678, 0.8901],
        top_k=3,
        filter=pipeline.vector_store.search("test", top_k=1)[0].chunk if False else None,
    )
    print("Generated pgvector Query SQL (<=> Cosine Distance Operator):")
    for line in sample_search_sql.strip().split("\n"):
        print(f"  {line}")
    print()
    print("=" * 72)
    print(" Demo completed successfully.")
    print("=" * 72)


def run_explain() -> None:
    """Print comprehensive theoretical guide on embeddings, similarity, and vector search."""
    print("""
================================================================================
 WEEK 9 — EMBEDDING & VECTOR SEARCH: ENGINEERING PRINCIPLES
================================================================================

1. WHAT IS AN EMBEDDING?
--------------------------------------------------------------------------------
An embedding is a representation of unstructured text as a dense vector of real
numbers in a continuous high-dimensional space (e.g. 128d, 384d, 1536d).
Unlike sparse keyword representations (TF-IDF/BM25) which rely on exact term
matching, dense embeddings capture semantic meaning and conceptual proximity.
Texts conveying equivalent meaning with zero vocabulary overlap (e.g. "reboot
router" and "restart the network gateway") map to vectors pointing in almost the
same geometric direction.

2. SIMILARITY METRICS COMPARISON
--------------------------------------------------------------------------------
Given vectors u and v in R^d:

a) Cosine Similarity:
   cos(theta) = (u . v) / (||u||_2 * ||v||_2)
   - Range: [-1.0, 1.0]
   - Invariant to vector length/scale; measures only angular direction.
   - Standard metric for semantic text search.

b) Cosine Distance (used by PostgreSQL pgvector '<=>' operator):
   distance = 1.0 - cosine_similarity(u, v)
   - Range: [0.0, 2.0]
   - 0.0 means identical angle; smaller distance means closer semantic match.

c) Euclidean Distance / L2 (pgvector '<->' operator):
   d(u, v) = sqrt(sum((u_i - v_i)^2))
   - Sensitive to vector magnitude. When vectors are unit-normalized (||v|| = 1),
     L2 distance^2 = 2 - 2 * cosine_similarity. Under normalization, L2 ranking
     is identical to Cosine ranking!

d) Dot Product / Inner Product (pgvector '<#>' operator):
   u . v = sum(u_i * v_i)
   - When vectors are unit-normalized, dot product equals cosine similarity.
   - Extremely fast to compute with SIMD / BLAS instructions.

3. CHUNKING STRATEGY: SIZE VS. OVERLAP
--------------------------------------------------------------------------------
Why chunk documents?
- Model limits: LLMs and embedding models have fixed context windows.
- Semantic dilution: A 30-page manual compressed into one vector becomes an
  undifferentiated average of too many topics ("needle in a haystack").
- Retrieval cost: Injecting 3 relevant 300-char paragraphs into prompt costs
  far fewer tokens than injecting whole documents.

Trade-offs:
- Chunk Size too small (e.g. 50 chars): fragmented sentences, lost context.
- Chunk Size too large (e.g. 2000 chars): unfocused vector representation.
- Chunk Overlap (typically 10-20%): ensures phrases or code blocks spanning
  chunk boundaries are not split and lost during search.
- Heading Breadcrumbs: prepending '[Parent > Heading]' keeps chunks grounded.

4. VECTOR SEARCH & INDEXING: FLAT vs. HNSW vs. IVFFLAT
--------------------------------------------------------------------------------
a) Flat (Exact k-NN):
   - Compares query vector against every stored vector (brute force).
   - Time complexity: O(N * d).
   - Recall: 100%. Best for small to medium collections (< 50,000 vectors).

b) IVFFlat (Inverted File Flat):
   - Partitions vector space into Voronoi cells using k-means clustering.
   - Searches only vectors within nearest centroid cells (probes).
   - Fast index build, low memory, trade-off in recall.

c) HNSW (Hierarchical Navigable Small World):
   - Multi-layer proximity graph resembling skip-lists.
   - Time complexity: O(log N).
   - Recall: > 95-98%. Fast query latency. Recommended for production pgvector.

5. METADATA FILTERING
--------------------------------------------------------------------------------
Semantic similarity does not replace business rules:
- Pre-filtering: Filter by metadata (e.g. category='openwrt') first, then search.
- Post-filtering: Search top-M nearest vectors, then discard non-matching metadata.
- Single-Stage (pgvector 0.5.0+): HNSW traversal evaluates SQL WHERE clauses
  iteratively, preventing recall degradation.
================================================================================
""")


def run_demo_cli() -> None:
    """Entrypoint for `vector-search-demo` console script."""
    run_demo()


def main() -> None:
    """Main CLI entrypoint for `vector-search-lab`."""
    parser = argparse.ArgumentParser(
        prog="vector-search-lab",
        description="Week 9 — Embedding + Vector Search Lab CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to run")

    # demo command
    demo_parser = subparsers.add_parser("demo", help="Run end-to-end vector search demo")
    demo_parser.add_argument("--data-dir", type=str, default=None, help="Path to docs directory")

    # explain command
    subparsers.add_parser("explain", help="Display engineering guide on embeddings and vector search")

    # search command
    search_parser = subparsers.add_parser("search", help="Execute vector search query")
    search_parser.add_argument("query", type=str, help="Search query string")
    search_parser.add_argument("--top-k", type=int, default=3, help="Number of results")
    search_parser.add_argument("--category", type=str, default=None, help="Filter by category")
    search_parser.add_argument("--data-dir", type=str, default=None, help="Path to docs directory")

    args = parser.parse_args()

    if args.command == "explain":
        run_explain()
    elif args.command == "search":
        data_path = Path(args.data_dir) if args.data_dir else get_default_data_dir()
        chunker = MarkdownChunker()
        embedder = MockEmbeddingProvider()
        store = InMemoryVectorStore()
        pipe = VectorSearchPipeline(chunker, embedder, store)
        pipe.ingest_directory(data_path)

        results = pipe.search(args.query, top_k=args.top_k, category=args.category)
        print(f"\nQuery: \"{args.query}\" [Found {len(results)} matches]:\n")
        for r in results:
            print(f"#{r.rank} [Score: {r.similarity:.4f} | Dist: {r.distance:.4f}] {r.chunk.heading}")
            print(f"   Source: {r.chunk.source_file}")
            print(f"   Snippet: {r.chunk.content[:200]}...\n")
    else:
        # Default action: run demo
        run_demo(Path(args.data_dir) if getattr(args, "data_dir", None) else None)


if __name__ == "__main__":
    main()
