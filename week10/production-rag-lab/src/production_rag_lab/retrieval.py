"""Retrieval orchestrator: one corpus, one chunk set, three comparable methods.

``ProductionRagRetriever`` loads the corpus exactly once, through the **public
Week 9 API only** (:class:`vector_search_lab.VectorSearchPipeline`,
:class:`vector_search_lab.MarkdownChunker`, :class:`vector_search_lab.Chunk`), and
then serves the *identical* chunk objects to:

* ``vector``  — dense cosine ranking from the Week 9 offline
  :class:`vector_search_lab.MockEmbeddingProvider`;
* ``bm25``    — the local :class:`production_rag_lab.lexical.BM25Index`;
* ``hybrid``  — RRF over the two rankings above.

No Week 9 file is modified, copied, or re-implemented. The mock embedder is a
deterministic hash projection: it demonstrates retrieval *mechanics* only and is
not a measure of production embedding quality.

Tie-breaking: the dense ranking is re-sorted by ``(-similarity, chunk_id)`` in the
Week 10 adapter, because the Week 9 store's ordering of equal similarities depends
on insertion order. The lexical ranking already sorts by ``(-score, chunk_id)``.

Reranking scope
---------------
The deterministic rules reranker reorders the **hybrid** top-10 candidates, so it is
defined only for ``method="hybrid"``. ``validate_rerank_combination`` is the single
source of truth for that rule and is enforced by :meth:`ProductionRagRetriever.search`
and by the CLI. Requesting it with ``vector`` or ``bm25`` raises ``ValueError``
rather than silently returning a hybrid result under the requested method's name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from vector_search_lab import (
    Chunk,
    Document,
    MarkdownChunker,
    MockEmbeddingProvider,
    VectorSearchPipeline,
)

from production_rag_lab.fusion import DEFAULT_RRF_C, FusedCandidate, reciprocal_rank_fusion
from production_rag_lab.lexical import BM25Index
from production_rag_lab.paths import get_default_data_dir
from production_rag_lab.rerank import DEFAULT_RERANK_CANDIDATES, rule_rerank

#: Supported retrieval methods.
METHODS: tuple[str, ...] = ("vector", "bm25", "hybrid")
#: Supported optional rerank modes (reported separately from base ``hybrid``).
RERANK_MODES: tuple[str, ...] = ("rules",)
#: The retrieval method each rerank mode is defined for.
RERANK_BASE_METHODS: Mapping[str, str] = {"rules": "hybrid"}
#: Candidates requested from each base retriever before fusion.
DEFAULT_CANDIDATE_DEPTH = 20
#: Default number of results returned to the caller.
DEFAULT_TOP_K = 3
#: Embedding dimension of the offline Week 9 mock provider used here.
EMBEDDING_DIMENSION = 128
#: Chunker configuration, matching the Week 9 demo defaults.
CHUNK_SIZE = 350
CHUNK_OVERLAP = 70

_SNIPPET_CHARS = 160


def validate_rerank_combination(method: str, rerank: str | None) -> None:
    """Validate a ``(method, rerank)`` pair, raising ``ValueError`` if unsupported.

    Rules reranking reorders the hybrid top-10 candidates, so it has no meaning for
    a single-retriever ranking. Accepting ``vector``/``bm25`` with ``rules`` would
    return hybrid results while reporting the requested method, which misstates
    which retrieval method produced the output.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; expected one of {METHODS}")
    if rerank is None:
        return
    if rerank not in RERANK_MODES:
        raise ValueError(
            f"Unknown rerank mode {rerank!r}; expected one of {RERANK_MODES}"
        )
    required = RERANK_BASE_METHODS[rerank]
    if method != required:
        raise ValueError(
            f"rerank={rerank!r} reranks the {required!r} top-"
            f"{DEFAULT_RERANK_CANDIDATES} candidates and is therefore only "
            f"supported with method={required!r}; got method={method!r}. Rules "
            "reranking cannot be applied to a single-retriever ranking because the "
            "fused candidates it reorders do not exist there. Use "
            f"method={required!r} --rerank {rerank} and compare it against the base "
            f"{required!r} ranking."
        )


def reported_mode(method: str, rerank: str | None) -> str:
    """Return the unambiguous label for a validated ``(method, rerank)`` pair.

    ``("hybrid", "rules")`` becomes ``"hybrid+rules"``; without reranking the label
    is just the method, so a reported mode never hides its base retrieval method.
    """
    return f"{method}+{rerank}" if rerank else method


def _snippet(text: str, limit: int = _SNIPPET_CHARS) -> str:
    """Collapse whitespace and truncate ``text`` for display."""
    return " ".join(text.split())[:limit]


def load_corpus_documents(data_dir: str | Path) -> tuple[Document, ...]:
    """Load the corpus as Week 9 ``Document`` objects, in sorted filename order.

    This mirrors Week 9's ``VectorSearchPipeline.ingest_directory`` conventions
    (sorted ``*.md``, ``title`` from the file stem, category inferred from the
    filename, ``doc_id`` equal to the file name) using only public Week 9 models.
    The document ID is what the gold labels reference, so it must stay exactly the
    source file name. Week 9 files themselves are only ever read.
    """
    folder = Path(data_dir)
    if not folder.is_dir():
        raise NotADirectoryError(f"Data directory not found: {folder}")

    documents: list[Document] = []
    for path in sorted(folder.glob("*.md")):
        lower_name = path.name.lower()
        if "openwrt" in lower_name:
            category = "openwrt"
        elif "esxi" in lower_name:
            category = "esxi"
        elif "docker" in lower_name:
            category = "docker"
        else:
            category = "general"
        documents.append(
            Document(
                id=path.name,
                title=path.stem.replace("_", " ").title(),
                content=path.read_text(encoding="utf-8"),
                category=category,
                source_file=path.name,
            )
        )
    return tuple(documents)


@dataclass(frozen=True)
class VectorHit:
    """One chunk in the dense ranking."""

    chunk_id: str
    doc_id: str
    similarity: float
    rank: int


@dataclass(frozen=True)
class RankedResult:
    """A single result returned to callers/CLI, with its explanation payload."""

    rank: int
    chunk_id: str
    doc_id: str
    title: str
    heading: str
    source_file: str
    category: str
    score: float
    score_kind: str
    snippet: str
    explanation: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "heading": self.heading,
            "source_file": self.source_file,
            "category": self.category,
            "score": round(self.score, 6),
            "score_kind": self.score_kind,
            "snippet": self.snippet,
            "explanation": self.explanation,
        }


class VectorAdapter:
    """Deterministic thin wrapper over the Week 9 offline vector pipeline.

    Week 9 is used as a black box through public APIs only. This adapter adds
    (a) a full-length ranking request, (b) an explicit ``chunk_id`` tie-break so
    identical similarities do not depend on insertion order, and (c) a
    consistency check proving the Week 10 chunk set and the Week 9 vector index
    describe exactly the same chunks.
    """

    def __init__(self, pipeline: VectorSearchPipeline, chunks: Sequence[Chunk]) -> None:
        self._pipeline = pipeline
        self._chunks = tuple(sorted(chunks, key=lambda c: c.chunk_id))
        if pipeline.chunk_count != len(self._chunks):
            raise RuntimeError(
                "Week 9 vector index holds "
                f"{pipeline.chunk_count} chunks but {len(self._chunks)} were chunked; "
                "the Week 10 chunker view and the Week 9 index disagree"
            )
        for chunk in self._chunks:
            if pipeline.vector_store.get(chunk.chunk_id) is None:
                raise RuntimeError(
                    f"Chunk {chunk.chunk_id} is absent from the Week 9 vector index"
                )

    @classmethod
    def from_documents(
        cls, documents: Sequence[Document]
    ) -> "VectorAdapter":
        """Build an adapter over already-loaded Week 9 ``Document`` objects."""
        chunker = MarkdownChunker(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        pipeline = VectorSearchPipeline(
            chunker=chunker,
            embedding_provider=MockEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
        )
        pipeline.ingest_documents(list(documents))
        chunks = [
            chunk
            for document in documents
            for chunk in chunker.chunk_document(document)
        ]
        return cls(pipeline, chunks)

    @classmethod
    def from_data_dir(cls, data_dir: str | Path | None = None) -> "VectorAdapter":
        """Build an adapter over the corpus in ``data_dir`` (Week 9 corpus default)."""
        target = Path(data_dir) if data_dir is not None else get_default_data_dir()
        return cls.from_documents(load_corpus_documents(target))

    @property
    def pipeline(self) -> VectorSearchPipeline:
        """The underlying Week 9 pipeline."""
        return self._pipeline

    @property
    def provider_name(self) -> str:
        """Human-readable name of the embedding provider actually in use."""
        return type(self._pipeline.embedding_provider).__name__

    @property
    def dimension(self) -> int:
        """Embedding dimension of the provider in use."""
        return self._pipeline.embedding_provider.dimension

    @property
    def doc_count(self) -> int:
        """Number of ingested documents."""
        return self._pipeline.doc_count

    @property
    def chunk_count(self) -> int:
        """Number of indexed chunks."""
        return self._pipeline.chunk_count

    def chunks(self) -> tuple[Chunk, ...]:
        """Return every indexed chunk in deterministic ``chunk_id`` order."""
        return self._chunks


    def rank(self, query: str) -> list[VectorHit]:
        """Return the full dense ranking for ``query``, best first.

        An empty/whitespace query returns no results, matching Week 9 behaviour.
        Similarities come from the Week 9 store (rounded to 4 decimals), so this
        ranking is deterministic and exactly reproducible.
        """
        if not query or not query.strip():
            return []
        results = self._pipeline.search(query, top_k=self.chunk_count)
        ordered = sorted(
            ((r.chunk.chunk_id, r.chunk.doc_id, r.similarity) for r in results),
            key=lambda item: (-item[2], item[0]),
        )
        return [
            VectorHit(chunk_id=chunk_id, doc_id=doc_id, similarity=similarity, rank=rank)
            for rank, (chunk_id, doc_id, similarity) in enumerate(ordered, start=1)
        ]


class ProductionRagRetriever:
    """Vector Only vs BM25 vs Hybrid over one shared corpus and query."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        rrf_c: int = DEFAULT_RRF_C,
        candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
        rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
    ) -> None:
        if candidate_depth <= 0:
            raise ValueError(f"candidate_depth must be positive, got {candidate_depth}")
        self._data_dir = Path(data_dir) if data_dir is not None else get_default_data_dir()
        self._vector = VectorAdapter.from_data_dir(self._data_dir)
        self._chunks: tuple[Chunk, ...] = self._vector.chunks()
        self._chunks_by_id: dict[str, Chunk] = {c.chunk_id: c for c in self._chunks}
        self._bm25 = BM25Index(self._chunks)
        self._rrf_c = rrf_c
        self._candidate_depth = candidate_depth
        self._rerank_candidates = rerank_candidates

    # ------------------------------------------------------------------ metadata

    @property
    def data_dir(self) -> Path:
        """Corpus directory this retriever was built from."""
        return self._data_dir

    @property
    def doc_count(self) -> int:
        """Number of corpus documents."""
        return len(self.document_ids)

    @property
    def chunk_count(self) -> int:
        """Number of corpus chunks (identical for every method)."""
        return len(self._chunks)

    @property
    def document_ids(self) -> tuple[str, ...]:
        """Sorted distinct document IDs in the corpus."""
        return tuple(sorted({chunk.doc_id for chunk in self._chunks}))

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        """All chunks in deterministic order."""
        return self._chunks

    @property
    def chunks_by_id(self) -> Mapping[str, Chunk]:
        """Read-only chunk lookup by ``chunk_id``."""
        return self._chunks_by_id

    @property
    def bm25_index(self) -> BM25Index:
        """The lexical index over the shared chunks."""
        return self._bm25

    @property
    def candidate_depth(self) -> int:
        """Candidates requested from each base retriever before fusion."""
        return self._candidate_depth

    @property
    def rrf_c(self) -> int:
        """RRF damping constant in use."""
        return self._rrf_c

    @property
    def vector_provider(self) -> str:
        """Name of the offline embedding provider in use."""
        return self._vector.provider_name

    # ----------------------------------------------------------------- rankings

    def _vector_ranking(self, query: str) -> list[tuple[str, str]]:
        depth = min(self._candidate_depth, self.chunk_count)
        return [
            (hit.chunk_id, hit.doc_id) for hit in self._vector.rank(query)[:depth]
        ]

    def _bm25_ranking(self, query: str) -> list[tuple[str, str]]:
        depth = min(self._candidate_depth, self.chunk_count)
        return self._bm25.rank_chunk_ids(query, depth)

    def ranking(self, query: str, method: str) -> list[tuple[str, str]]:
        """Return the full ``(chunk_id, doc_id)`` ranking for one method.

        Length equals the number of candidates that method can supply, so callers
        can tell an exhausted ranking from a truncated one.
        """
        if method not in METHODS:
            raise ValueError(f"Unknown method {method!r}; expected one of {METHODS}")
        if not query or not query.strip():
            return []
        if method == "vector":
            return self._vector_ranking(query)
        if method == "bm25":
            return self._bm25_ranking(query)
        return self.fused_ranking(query)

    def fused_ranking(self, query: str) -> list[tuple[str, str]]:
        """Return the full RRF hybrid ranking as ``(chunk_id, doc_id)`` pairs."""
        if not query or not query.strip():
            return []
        return [
            (candidate.chunk_id, candidate.doc_id)
            for candidate in self.fuse(query)
        ]

    def fuse(self, query: str) -> list[FusedCandidate]:
        """Return every fused hybrid candidate with ranks and contributions."""
        return reciprocal_rank_fusion(
            {"vector": self._vector_ranking(query), "bm25": self._bm25_ranking(query)},
            c=self._rrf_c,
        )

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str,
        *,
        method: str = "hybrid",
        top_k: int = DEFAULT_TOP_K,
        rerank: str | None = None,
    ) -> list[RankedResult]:
        """Run one retrieval and return up to ``top_k`` explained results.

        Args:
            query: user query; empty/whitespace returns no results for every method.
            method: one of :data:`METHODS`.
            top_k: number of results to return.
            rerank: ``None`` (no reranking) or ``"rules"``. The reranked output is
                a separate mode and never replaces the base method's ranking.

        Raises:
            ValueError: for an unknown method or rerank mode, or for a rerank mode
                that is not defined for ``method`` — see
                :func:`validate_rerank_combination`.
        """
        validate_rerank_combination(method, rerank)
        if top_k <= 0:
            return []
        if not query or not query.strip():
            return []

        if rerank is not None:
            # Only reachable for method="hybrid"; the rule reranker reorders the
            # fused top-10 and its results always declare that hybrid base.
            return self._search_reranked(query, top_k=top_k)
        if method == "vector":
            return self._search_vector(query, top_k=top_k)
        if method == "bm25":
            return self._search_bm25(query, top_k=top_k)
        return self._search_hybrid(query, top_k=top_k)

    def _base_result(
        self, rank: int, chunk: Chunk, score: float, kind: str, explanation: dict
    ) -> RankedResult:
        return RankedResult(
            rank=rank,
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            title=chunk.title,
            heading=chunk.heading,
            source_file=chunk.source_file,
            category=chunk.category,
            score=score,
            score_kind=kind,
            snippet=_snippet(chunk.content),
            explanation=explanation,
        )

    def _search_vector(self, query: str, *, top_k: int) -> list[RankedResult]:
        depth = min(self._candidate_depth, self.chunk_count)
        hits = self._vector.rank(query)[:depth]
        results = []
        for hit in hits[:top_k]:
            chunk = self._chunks_by_id[hit.chunk_id]
            results.append(
                self._base_result(
                    hit.rank,
                    chunk,
                    hit.similarity,
                    "cosine_similarity",
                    {
                        "provider": self._vector.provider_name,
                        "dimension": self._vector.dimension,
                        "candidate_rank": hit.rank,
                        "note": (
                            "MockEmbeddingProvider is a deterministic offline hash "
                            "projection, not a learned semantic model."
                        ),
                    },
                )
            )
        return results

    def _search_bm25(self, query: str, *, top_k: int) -> list[RankedResult]:
        depth = min(self._candidate_depth, self.chunk_count)
        hits = self._bm25.search(query, top_k=depth)
        results = []
        for hit in hits[:top_k]:
            chunk = self._chunks_by_id[hit.chunk_id]
            results.append(
                self._base_result(
                    hit.rank,
                    chunk,
                    hit.score,
                    "bm25",
                    {
                        "k1": self._bm25.k1,
                        "b": self._bm25.b,
                        "matched_terms": list(hit.matched_terms),
                        "candidate_rank": hit.rank,
                    },
                )
            )
        return results

    def _search_hybrid(self, query: str, *, top_k: int) -> list[RankedResult]:
        candidates = self.fuse(query)[: min(self._candidate_depth, self.chunk_count)]
        results = []
        for position, candidate in enumerate(candidates[:top_k], start=1):
            chunk = self._chunks_by_id[candidate.chunk_id]
            results.append(
                self._base_result(
                    position,
                    chunk,
                    candidate.score,
                    "rrf",
                    {
                        "c": self._rrf_c,
                        "methods": list(candidate.methods),
                        "fused": candidate.as_dict(),
                    },
                )
            )
        return results

    def _search_reranked(self, query: str, *, top_k: int) -> list[RankedResult]:
        """Rerank the hybrid top-10; only reachable for ``method="hybrid"``."""
        base_method = RERANK_BASE_METHODS["rules"]
        fused = self.fuse(query)[: min(self._rerank_candidates, self.chunk_count)]
        reranked = rule_rerank(query, fused, self._chunks_by_id)
        results = []
        for position, item in enumerate(reranked[:top_k], start=1):
            chunk = self._chunks_by_id[item.chunk_id]
            results.append(
                self._base_result(
                    position,
                    chunk,
                    item.rrf_score,
                    "rules_rerank",
                    {
                        # Provenance: these results are a permutation of the
                        # hybrid top-N fused candidates, never a reranking of a
                        # single retriever's ranking.
                        "mode": reported_mode(base_method, "rules"),
                        "base_method": base_method,
                        "rerank": "rules",
                        "c": self._rrf_c,
                        "candidate_limit": self._rerank_candidates,
                        "features": item.as_dict(),
                    },
                )
            )
        return results
