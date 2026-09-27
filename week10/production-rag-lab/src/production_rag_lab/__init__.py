"""Week 10 — Production RAG Lab.

Offline, deterministic comparison of three retrieval strategies over one shared
Week 9 corpus, one shared chunk set, and one shared query set:

* ``vector``  — dense cosine retrieval (Week 9 ``MockEmbeddingProvider``)
* ``bm25``    — lexical Okapi BM25 retrieval
* ``hybrid``  — Reciprocal Rank Fusion (RRF) of the two rankings above

An optional bounded deterministic rule reranker is available as a **separate**
mode (``hybrid+rules``) and is never merged into the base ``hybrid`` numbers.

Everything runs locally: no network access, no API key, no hosted model, and no
database. The Week 9 lab is consumed as an editable local path dependency and its
files are never modified.

Evaluation is **document-level**: chunks are ranked first, the ranked chunk list is
collapsed to unique document IDs in first-occurrence order, and the cutoff ``k``
counts those unique documents.
"""

from production_rag_lab.evaluation import (
    DEFAULT_KS,
    EXPECTED_QUERY_COUNT,
    EvalDataError,
    EvalQuery,
    EvalReport,
    MethodReport,
    QueryOutcome,
    collapse_to_unique_documents,
    evaluate,
    file_sha256,
    hit_at_k,
    load_queries,
    validate_gold_doc_ids,
)
from production_rag_lab.fusion import (
    DEFAULT_RRF_C,
    FusedCandidate,
    reciprocal_rank_fusion,
)
from production_rag_lab.lexical import (
    DEFAULT_B,
    DEFAULT_K1,
    TOKENIZER_VERSION,
    BM25Explanation,
    BM25Index,
    BM25TermContribution,
    index_text,
    normalize_text,
    tokenize,
    unique_tokens,
)
from production_rag_lab.paths import (
    get_default_data_dir,
    get_default_queries_path,
)
from production_rag_lab.rerank import (
    DEFAULT_RERANK_CANDIDATES,
    RerankedCandidate,
    rule_rerank,
)
from production_rag_lab.retrieval import (
    DEFAULT_CANDIDATE_DEPTH,
    DEFAULT_TOP_K,
    METHODS,
    RERANK_BASE_METHODS,
    RERANK_MODES,
    ProductionRagRetriever,
    RankedResult,
    VectorAdapter,
    VectorHit,
    reported_mode,
    validate_rerank_combination,
)

__version__ = "0.1.0"

__all__ = [
    "BM25Explanation",
    "BM25Index",
    "BM25TermContribution",
    "DEFAULT_B",
    "DEFAULT_CANDIDATE_DEPTH",
    "DEFAULT_K1",
    "DEFAULT_KS",
    "DEFAULT_RERANK_CANDIDATES",
    "DEFAULT_RRF_C",
    "DEFAULT_TOP_K",
    "EXPECTED_QUERY_COUNT",
    "EvalDataError",
    "EvalQuery",
    "EvalReport",
    "FusedCandidate",
    "METHODS",
    "MethodReport",
    "ProductionRagRetriever",
    "QueryOutcome",
    "RERANK_BASE_METHODS",
    "RERANK_MODES",
    "RankedResult",
    "RerankedCandidate",
    "TOKENIZER_VERSION",
    "VectorAdapter",
    "VectorHit",
    "__version__",
    "collapse_to_unique_documents",
    "evaluate",
    "file_sha256",
    "get_default_data_dir",
    "get_default_queries_path",
    "hit_at_k",
    "index_text",
    "load_queries",
    "normalize_text",
    "reciprocal_rank_fusion",
    "reported_mode",
    "rule_rerank",
    "tokenize",
    "unique_tokens",
    "validate_gold_doc_ids",
    "validate_rerank_combination",
]
