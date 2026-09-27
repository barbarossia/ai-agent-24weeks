"""Reciprocal Rank Fusion (RRF) for combining an independent dense and lexical ranking.

Why rank fusion instead of adding scores
---------------------------------------
A BM25 score (unbounded, corpus-dependent) and a cosine similarity (bounded in
``[-1, 1]``) are **not comparable quantities**. Adding or weighting them directly
would silently mix two different scales. RRF (Cormack, Clarke & Büttcher, SIGIR
2009) fuses the *rankings* instead::

    RRF(d) = Σ_r  1 / (c + rank_r(d))

with the constant ``c = 60`` as used in the original paper. Because only ranks
enter the formula, no score calibration is required. The paper's empirical results
come from its own test collections; nothing here claims RRF will win on this
four-document teaching corpus.

Determinism
-----------
* Ranks are 1-based and taken from the position in each input ranking.
* A chunk missing from a ranking contributes nothing from that ranking (rank 0 is
  never inserted).
* Duplicate ``chunk_id`` values inside one input ranking are collapsed to their
  first occurrence, so a repeated chunk cannot occupy two ranks.
* Fused candidates are ordered by score descending, then best vector rank
  ascending, then best BM25 rank ascending, then ``chunk_id`` ascending. Missing
  ranks sort last, so a chunk found by only one retriever never outranks a tie
  broken by an earlier position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

#: RRF damping constant, fixed at the value used by Cormack et al. (SIGIR 2009).
DEFAULT_RRF_C = 60

#: Deterministic tie-break order after the fused score.
DEFAULT_TIE_BREAK_METHODS: tuple[str, ...] = ("vector", "bm25")


@dataclass(frozen=True)
class FusedCandidate:
    """One chunk after rank fusion, with full per-retriever provenance."""

    chunk_id: str
    doc_id: str
    score: float
    ranks: Mapping[str, int]
    contributions: Mapping[str, float]

    @property
    def methods(self) -> tuple[str, ...]:
        """Retriever names that contributed a rank, in sorted order."""
        return tuple(sorted(self.ranks))

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "rrf_score": round(self.score, 6),
            "ranks": {name: self.ranks[name] for name in sorted(self.ranks)},
            "contributions": {
                name: round(self.contributions[name], 6)
                for name in sorted(self.contributions)
            },
        }


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[tuple[str, str]]],
    *,
    c: int = DEFAULT_RRF_C,
    top_k: int | None = None,
    tie_break_methods: Sequence[str] = DEFAULT_TIE_BREAK_METHODS,
) -> list[FusedCandidate]:
    """Fuse per-retriever ``(chunk_id, doc_id)`` rankings with RRF.

    Args:
        rankings: mapping of retriever name to its ranked ``(chunk_id, doc_id)``
            pairs, best first. An empty ranking contributes nothing.
        c: RRF damping constant (default and expected value: 60).
        top_k: return only the first ``top_k`` fused candidates; ``None`` returns
            the whole fused list.
        tie_break_methods: retriever names consulted, in order, for the stable
            tie-break after the fused score. A missing rank sorts last.

    Returns:
        Fused candidates ordered by score descending and the documented
        deterministic tie-breaks.
    """
    if c < 0:
        raise ValueError(f"c must be non-negative, got {c}")
    if top_k is not None and top_k <= 0:
        raise ValueError(f"top_k must be positive when provided, got {top_k}")

    ranks: dict[str, dict[str, int]] = {}
    doc_ids: dict[str, str] = {}
    for method in sorted(rankings):
        seen: set[str] = set()
        method_ranks: dict[str, int] = {}
        position = 0
        for chunk_id, doc_id in rankings[method]:
            if chunk_id in seen:
                # Duplicate inside one ranking: keep only the first occurrence so
                # a repeated chunk cannot occupy two ranks.
                continue
            seen.add(chunk_id)
            position += 1
            method_ranks[chunk_id] = position
            doc_ids[chunk_id] = doc_id
        ranks[method] = method_ranks

    def sort_key(candidate: FusedCandidate) -> tuple[object, ...]:
        key: list[object] = [-candidate.score]
        for method in tie_break_methods:
            key.append(candidate.ranks.get(method, float("inf")))
        key.append(candidate.chunk_id)
        return tuple(key)

    candidates: list[FusedCandidate] = []
    for chunk_id in sorted(doc_ids):
        chunk_ranks = {
            method: method_ranks[chunk_id]
            for method, method_ranks in ranks.items()
            if chunk_id in method_ranks
        }
        if not chunk_ranks:
            continue
        contributions = {
            method: 1.0 / (c + rank) for method, rank in chunk_ranks.items()
        }
        candidates.append(
            FusedCandidate(
                chunk_id=chunk_id,
                doc_id=doc_ids[chunk_id],
                score=sum(contributions[method] for method in sorted(contributions)),
                ranks=chunk_ranks,
                contributions=contributions,
            )
        )

    candidates.sort(key=sort_key)
    if top_k is not None:
        return candidates[:top_k]
    return candidates
