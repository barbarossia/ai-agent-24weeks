"""Gold-labeled query loading and the authoritative **document-level** Hit@k metric.

The metric contract (accepted by the task's research review)
-----------------------------------------------------------
Methods rank **chunks**. For each method and each query:

1. Walk the ranked chunks in order and keep only the **first occurrence** of each
   ``doc_id``; this collapses the chunk ranking to a list of unique document IDs.
2. Let ``R_q(k)`` be the first ``k`` unique document IDs. The cutoff ``k``
   therefore counts **unique documents, not chunks**.
3. ``hit_q@k = 1`` if ``R_q(k) ∩ G_q`` is non-empty, else ``0``, where ``G_q`` is
   the query's ``gold_doc_ids``.
4. ``macro Hit@k = (Σ_q hit_q@k) / Q`` — every query carries equal weight.

A query with no results is a miss; the list is never padded. This is a binary
"any gold document retrieved" metric: it is **not** precision, and chunk-level
Hit@k is explicitly out of scope for this lab.

Gold labels are fixed inputs. They are validated against the corpus (unknown gold
document IDs are an error, never a silent remap) and they are never derived from,
or adjusted because of, system output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

#: Number of rows the fixed, reviewed query set must contain.
EXPECTED_QUERY_COUNT = 24
#: Default cutoffs reported by the CLI.
DEFAULT_KS: tuple[int, ...] = (1, 3)

#: A ranked result as consumed by the metric: ``(chunk_id, doc_id)``.
RankedPair = tuple[str, str]


class EvalDataError(ValueError):
    """Raised when the query file or gold labels are invalid."""


@dataclass(frozen=True)
class EvalQuery:
    """One fixed evaluation question with its gold document labels."""

    query_id: str
    query: str
    gold_doc_ids: tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True)
class QueryOutcome:
    """Per-query evaluation detail (retrieved documents and binary hit flags)."""

    query_id: str
    gold_doc_ids: tuple[str, ...]
    retrieved_doc_ids: tuple[str, ...]
    hit_at_k: Mapping[int, bool]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "query_id": self.query_id,
            "gold_doc_ids": list(self.gold_doc_ids),
            "retrieved_doc_ids": list(self.retrieved_doc_ids),
            "hit_at_k": {str(k): self.hit_at_k[k] for k in sorted(self.hit_at_k)},
        }


@dataclass(frozen=True)
class MethodReport:
    """Macro document-level Hit@k for one method, plus per-query detail."""

    method: str
    macro_hit_at_k: Mapping[int, float]
    per_query: tuple[QueryOutcome, ...]

    def hits(self, k: int) -> int:
        """Number of queries that hit at cutoff ``k``."""
        return sum(1 for outcome in self.per_query if outcome.hit_at_k[k])

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "method": self.method,
            "macro_hit_at_k": {
                str(k): round(self.macro_hit_at_k[k], 6) for k in sorted(self.macro_hit_at_k)
            },
            "hit_counts": {str(k): self.hits(k) for k in sorted(self.macro_hit_at_k)},
            "query_count": len(self.per_query),
            "per_query": [outcome.as_dict() for outcome in self.per_query],
        }


@dataclass(frozen=True)
class EvalReport:
    """Complete evaluation result for every method under test."""

    ks: tuple[int, ...]
    query_count: int
    methods: tuple[MethodReport, ...]

    def method(self, name: str) -> MethodReport:
        """Return the report for ``name``."""
        for report in self.methods:
            if report.method == name:
                return report
        raise KeyError(name)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view with deterministic key order."""
        return {
            "ks": list(self.ks),
            "query_count": self.query_count,
            "methods": [report.as_dict() for report in self.methods],
        }


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 hex digest of ``path`` (used to pin the query set)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_str(payload: dict, key: str, line_number: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalDataError(
            f"line {line_number}: field {key!r} must be a non-empty string"
        )
    return value


def load_queries(path: str | Path) -> tuple[EvalQuery, ...]:
    """Load and validate the fixed JSONL query set.

    Rejects: a missing/empty file, malformed JSON, non-object rows, blank
    ``query_id``/``query``, duplicate ``query_id`` values, and empty or malformed
    ``gold_doc_ids`` lists. Row order in the file is preserved, which keeps
    per-query output stable.
    """
    source = Path(path)
    if not source.is_file():
        raise EvalDataError(f"Query file not found: {source}")

    raw = source.read_text(encoding="utf-8")
    if not raw.strip():
        raise EvalDataError(f"Query file is empty: {source}")

    queries: list[EvalQuery] = []
    seen: dict[str, int] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalDataError(f"line {line_number}: invalid JSON ({exc.msg})") from exc
        if not isinstance(payload, dict):
            raise EvalDataError(f"line {line_number}: expected a JSON object")

        query_id = _require_str(payload, "query_id", line_number)
        query = _require_str(payload, "query", line_number)

        gold = payload.get("gold_doc_ids")
        if not isinstance(gold, list) or not gold:
            raise EvalDataError(
                f"line {line_number}: field 'gold_doc_ids' must be a non-empty list"
            )
        gold_ids: list[str] = []
        for entry in gold:
            if not isinstance(entry, str) or not entry.strip():
                raise EvalDataError(
                    f"line {line_number}: 'gold_doc_ids' entries must be non-empty strings"
                )
            if entry not in gold_ids:
                gold_ids.append(entry)

        if query_id in seen:
            raise EvalDataError(
                f"line {line_number}: duplicate query_id {query_id!r} "
                f"(first seen on line {seen[query_id]})"
            )
        seen[query_id] = line_number

        notes = payload.get("notes", "")
        if not isinstance(notes, str):
            raise EvalDataError(f"line {line_number}: field 'notes' must be a string")

        queries.append(
            EvalQuery(
                query_id=query_id,
                query=query,
                gold_doc_ids=tuple(gold_ids),
                notes=notes,
            )
        )

    if not queries:
        raise EvalDataError(f"Query file contains no queries: {source}")
    return tuple(queries)


def validate_gold_doc_ids(
    queries: Sequence[EvalQuery], known_doc_ids: Iterable[str]
) -> None:
    """Fail loudly when a gold label does not exist in the corpus.

    A missing document ID means the corpus changed and the labels must be
    re-reviewed by a human; they are never remapped automatically.
    """
    known = set(known_doc_ids)
    if not known:
        raise EvalDataError("Corpus contains no documents to validate gold labels against")
    problems = [
        f"{query.query_id} -> {doc_id!r}"
        for query in queries
        for doc_id in query.gold_doc_ids
        if doc_id not in known
    ]
    if problems:
        raise EvalDataError(
            "Unknown gold document ID(s) for the current corpus: "
            + ", ".join(sorted(problems))
            + ". Re-review the labels; do not remap them automatically."
        )


def collapse_to_unique_documents(ranked: Sequence[RankedPair]) -> tuple[str, ...]:
    """Collapse a ranked chunk list to unique document IDs in first-hit order."""
    seen: set[str] = set()
    documents: list[str] = []
    for _chunk_id, doc_id in ranked:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        documents.append(doc_id)
    return tuple(documents)


def hit_at_k(
    retrieved_doc_ids: Sequence[str], gold_doc_ids: Sequence[str], k: int
) -> bool:
    """Return whether any gold document is among the first ``k`` unique documents.

    ``k`` counts unique documents. An empty result list, or ``k <= 0``, is a miss.
    """
    if k <= 0:
        return False
    gold = set(gold_doc_ids)
    if not gold:
        return False
    return any(doc_id in gold for doc_id in list(retrieved_doc_ids)[:k])


def check_candidate_depth(
    method: str,
    query_id: str,
    *,
    candidate_count: int,
    unique_doc_count: int,
    ks: Sequence[int],
    candidate_cap: int,
    corpus_chunk_count: int,
    corpus_doc_count: int,
    cap_is_method_definition: bool = False,
) -> None:
    """Verify a ranking exposes enough unique documents for the requested cutoffs.

    A ranking that returns **fewer** candidates than it could have is *exhausted*:
    a short unique-document list is then a genuine retrieval outcome (for example
    BM25 finds no lexical match outside two documents) and is reported as a miss.

    Only a ranking that was actually truncated at the candidate cap can silently
    understate recall, and that case is an error — unless the cap *is* the method's
    reviewed definition. The bounded deterministic reranker deliberately reranks
    only the hybrid top-10, so it can never surface a document absent from that
    window; ``cap_is_method_definition=True`` records that this is intended
    behaviour of the method rather than a retrieval-budget accident.
    """
    if not ks or cap_is_method_definition:
        return
    cap = min(candidate_cap, corpus_chunk_count)
    if candidate_count < cap:
        # Exhausted ranking: nothing was withheld, so the metric is trustworthy.
        return
    needed = min(max(ks), corpus_doc_count)
    if unique_doc_count < needed:
        raise EvalDataError(
            f"{method}/{query_id}: ranking was truncated at {cap} candidates and "
            f"exposes only {unique_doc_count} unique documents, but cutoff "
            f"k={max(ks)} needs {needed} (increase the candidate depth)"
        )


def evaluate(
    queries: Sequence[EvalQuery],
    rankings: Mapping[str, Mapping[str, Sequence[RankedPair]]],
    ks: Sequence[int] = DEFAULT_KS,
) -> EvalReport:
    """Compute macro document-level Hit@k for every method.

    Args:
        queries: the fixed gold-labeled questions, in file order.
        rankings: ``{method: {query_id: ranked (chunk_id, doc_id) pairs}}``.
        ks: cutoffs counting **unique documents**.

    Returns:
        An :class:`EvalReport` whose method order follows ``rankings`` order, so
        output is byte-stable across runs.
    """
    cutoffs = tuple(sorted({int(k) for k in ks}))
    if not cutoffs:
        raise EvalDataError("At least one cutoff k is required")
    if any(k <= 0 for k in cutoffs):
        raise EvalDataError(f"Cutoffs must be positive, got {list(cutoffs)}")
    if not queries:
        raise EvalDataError("No queries to evaluate")

    query_ids = {query.query_id for query in queries}
    reports: list[MethodReport] = []
    for method, per_query_rankings in rankings.items():
        missing = sorted(query_ids - set(per_query_rankings))
        if missing:
            raise EvalDataError(
                f"Method {method!r} has no ranking for query id(s): {', '.join(missing)}"
            )
        outcomes: list[QueryOutcome] = []
        for query in queries:
            ranked = per_query_rankings[query.query_id]
            retrieved = collapse_to_unique_documents(ranked)
            outcomes.append(
                QueryOutcome(
                    query_id=query.query_id,
                    gold_doc_ids=query.gold_doc_ids,
                    retrieved_doc_ids=retrieved,
                    hit_at_k={
                        k: hit_at_k(retrieved, query.gold_doc_ids, k) for k in cutoffs
                    },
                )
            )
        reports.append(
            MethodReport(
                method=method,
                macro_hit_at_k={
                    k: sum(1 for o in outcomes if o.hit_at_k[k]) / len(outcomes)
                    for k in cutoffs
                },
                per_query=tuple(outcomes),
            )
        )

    return EvalReport(ks=cutoffs, query_count=len(queries), methods=tuple(reports))
