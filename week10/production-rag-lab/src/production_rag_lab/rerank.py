"""Bounded, deterministic rule-based reranking of hybrid candidates.

This is a **teaching reranker**, not a neural cross-encoder. It uses only
explainable, offline signals over the *same* chunk text the lexical index uses:

1. ``exact_phrase_match`` — the whitespace-normalized lowercase query occurs as a
   substring of the normalized chunk field;
2. ``matched_token_count`` — how many **distinct** query tokens occur in the chunk
   token set (produced by the shared ``week10-mixed-cjk-v1`` tokenizer);
3. the incoming fused ``rrf_score``;
4. ``chunk_id`` ascending, as the final stable tie-break.

Bounds
------
The candidate set is capped at :data:`DEFAULT_RERANK_CANDIDATES` (10) hybrid
candidates and the function refuses a larger input. The output is a permutation of
the input: no candidate can be invented, dropped, or promoted from outside the
supplied set. Results are therefore reported **separately** from the base
``hybrid`` ranking so the effect of reranking stays isolated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from vector_search_lab import Chunk

from production_rag_lab.fusion import FusedCandidate
from production_rag_lab.lexical import normalize_text, tokenize, unique_tokens

#: Maximum number of hybrid candidates that may be reranked.
DEFAULT_RERANK_CANDIDATES = 10


@dataclass(frozen=True)
class RerankedCandidate:
    """One reranked candidate with the deterministic features that ordered it."""

    position: int
    chunk_id: str
    doc_id: str
    rrf_score: float
    exact_phrase_match: bool
    matched_token_count: int
    matched_tokens: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "position": self.position,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "rrf_score": round(self.rrf_score, 6),
            "exact_phrase_match": self.exact_phrase_match,
            "matched_token_count": self.matched_token_count,
            "matched_tokens": list(self.matched_tokens),
        }


def _default_chunk_text(chunk: Chunk) -> str:
    """Chunk text used for rerank features: the same uniform lexical field."""
    return "\n".join(
        part for part in (chunk.title, chunk.heading, chunk.content) if part
    )


def rule_rerank(
    query: str,
    candidates: Sequence[FusedCandidate],
    chunks_by_id: Mapping[str, Chunk],
    *,
    max_candidates: int = DEFAULT_RERANK_CANDIDATES,
    chunk_text: Callable[[Chunk], str] = _default_chunk_text,
) -> list[RerankedCandidate]:
    """Rerank at most ``max_candidates`` fused candidates with deterministic rules.

    Args:
        query: the original user query.
        candidates: fused hybrid candidates (already truncated by the caller).
        chunks_by_id: lookup from ``chunk_id`` to the Week 9 ``Chunk``.
        max_candidates: hard upper bound on the candidate set; a larger input is a
            programming error and raises ``ValueError``.
        chunk_text: text extractor for feature computation.

    Returns:
        A permutation of ``candidates``, best first, with the ordering features
        recorded for explanation.
    """
    if len(candidates) > max_candidates:
        raise ValueError(
            f"rule_rerank accepts at most {max_candidates} candidates, "
            f"got {len(candidates)}"
        )
    if max_candidates <= 0:
        raise ValueError(f"max_candidates must be positive, got {max_candidates}")

    query_tokens = unique_tokens(query)
    normalized_query = normalize_text(query)

    scored: list[tuple[tuple[object, ...], FusedCandidate, bool, int, tuple[str, ...]]] = []
    for candidate in candidates:
        chunk = chunks_by_id[candidate.chunk_id]
        text = normalize_text(chunk_text(chunk))
        phrase_match = bool(normalized_query) and normalized_query in text
        chunk_tokens = set(tokenize(chunk_text(chunk)))
        matched = tuple(term for term in query_tokens if term in chunk_tokens)
        key: tuple[object, ...] = (
            0 if phrase_match else 1,
            -len(matched),
            -candidate.score,
            candidate.chunk_id,
        )
        scored.append((key, candidate, phrase_match, len(matched), matched))

    scored.sort(key=lambda item: item[0])

    return [
        RerankedCandidate(
            position=position,
            chunk_id=candidate.chunk_id,
            doc_id=candidate.doc_id,
            rrf_score=candidate.score,
            exact_phrase_match=phrase_match,
            matched_token_count=matched_count,
            matched_tokens=matched,
        )
        for position, (_, candidate, phrase_match, matched_count, matched) in enumerate(
            scored, start=1
        )
    ]
