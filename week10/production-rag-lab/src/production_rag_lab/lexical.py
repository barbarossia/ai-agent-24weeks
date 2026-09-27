"""Deterministic mixed English/Chinese tokenizer and a bounded pure-Python BM25 index.

Tokenizer contract (``week10-mixed-cjk-v1``)
-------------------------------------------
Input text is lowercased with Python's Unicode ``str.lower()``. The text is then
scanned **once, left to right**, with a single alternation regex, so tokens are
emitted in text order and the output is fully deterministic:

* ASCII runs matching ``[a-z0-9_./-]+`` are emitted as one compound token. This
  keeps technical identifiers intact: ``ubus-over-http``, ``network.interface.dump``,
  ``esxcli``, ``pg_isready``, ``192.168.1.50``, ``-32002``.
* A compound ASCII token that contains ``-`` additionally emits its non-empty
  components, so ``ubus-over-http`` also yields ``ubus``, ``over`` and ``http``.
  Dots, underscores and slashes are **not** split: they are meaningful inside the
  identifiers that appear in this corpus, and the Week 9 mock embedder keeps them
  whole as well.
* CJK ideograph runs (U+4E00–U+9FFF) are emitted per run as: every character in
  order (unigrams), then every adjacent character pair in order (bigrams). Bigrams
  never cross a run boundary, so punctuation and Latin text break them.
* A run that contains no ASCII alphanumeric character is dropped, so pure
  punctuation, bullets, and arrows never become tokens.
* Whitespace and every other character (including CJK punctuation such as ``，``
  and ``。``) are ignored.

Example: ``"VMFS 数据存储"`` -> ``['vmfs', '数', '据', '存', '储', '数据', '据存', '存储']``.

This is an intentionally small teaching baseline: CJK **character** unigrams and
bigrams are **not** Chinese word segmentation, and they are not claimed to be
linguistically correct. They exist so that a mixed corpus can be matched
lexically with no extra dependency, mirroring the feature space of the Week 9
offline mock embedder.

BM25 contract
-------------
For indexed chunk ``d``, query ``q`` and each **distinct** query term ``t``::

    idf(t)   = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
    score(d) = Σ_t idf(t) * tf(t,d) * (k1 + 1)
                        / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

with ``k1 = 1.5`` and ``b = 0.75``. ``N`` is the number of indexed chunks, ``df``
the number of chunks containing the term, ``tf`` the token count, ``|d|`` and
``avgdl`` token counts.

Notes that are deliberate and documented rather than accidental:

* The IDF variant above is a common *nonnegative smoothed* form. BM25 has several
  legitimate IDF variants and this is not claimed to be the only canonical one.
* ``k1``/``b`` are explicit defaults, fixed **before** any gold label was scored,
  and are never tuned against the evaluation queries.
* Each distinct query term is scored once; repeating a term in the query does not
  multiply its weight.
* Chunk length and all corpus statistics are computed on exactly the same
  normalized index text (:func:`index_text`) used for matching, with a single
  uniform field ``title + heading + content`` and no field-specific boosts.
* Only chunks with ``score > 0`` are returned, so a query with no matching term
  yields no results rather than a full corpus of zeros.
* Term summation order and candidate order are fixed (sorted), so floating-point
  results are bit-for-bit reproducible.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from vector_search_lab import Chunk

#: Version tag of the tokenizer contract described in this module's docstring.
TOKENIZER_VERSION = "week10-mixed-cjk-v1"

#: BM25 term-frequency saturation parameter (explicit default, not tuned).
DEFAULT_K1 = 1.5
#: BM25 length-normalization parameter (explicit default, not tuned).
DEFAULT_B = 0.75

_CJK_PATTERN = "\u4e00-\u9fff"
# Left-to-right alternation: ASCII compound run, or a contiguous CJK ideograph run.
_SEGMENT_RE = re.compile(f"[a-z0-9_./-]+|[{_CJK_PATTERN}]+")
_ALNUM_RE = re.compile(r"[a-z0-9]")
_CJK_CHAR_RE = re.compile(f"[{_CJK_PATTERN}]")
_WHITESPACE_RE = re.compile(r"\s+")


def tokenize(text: str) -> list[str]:
    """Tokenize mixed English/Chinese ``text`` per the ``week10-mixed-cjk-v1`` contract.

    Returns tokens in emission order. An empty or punctuation-only string returns
    an empty list.
    """
    if not text:
        return []

    tokens: list[str] = []
    for match in _SEGMENT_RE.finditer(text.lower()):
        segment = match.group(0)
        is_cjk_run = _CJK_CHAR_RE.search(segment) is not None
        if not is_cjk_run and _ALNUM_RE.search(segment) is None:
            # Pure punctuation run (e.g. "...", "->", "/"): not a token.
            continue

        if is_cjk_run:
            # CJK run: unigrams in order, then adjacent bigrams in order.
            for char in segment:
                tokens.append(char)
            for i in range(len(segment) - 1):
                tokens.append(segment[i] + segment[i + 1])
        else:
            # ASCII compound run, kept intact so technical identifiers survive.
            tokens.append(segment)
            # Hyphen-separated identifier components are added as extra tokens so a
            # query using only one part of a compound identifier can still match.
            if "-" in segment:
                for component in segment.split("-"):
                    if component and _ALNUM_RE.search(component) is not None:
                        tokens.append(component)

    return tokens


def unique_tokens(text: str) -> list[str]:
    """Return the distinct tokens of ``text`` in sorted order.

    Sorting makes term summation order independent of the order a caller happened
    to write the query in, which keeps BM25 scores reproducible.
    """
    return sorted(set(tokenize(text)))


def normalize_text(text: str) -> str:
    """Lowercase ``text`` and collapse whitespace runs to single spaces."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def index_text(chunk: Chunk) -> str:
    """Return the single uniform lexical field indexed for ``chunk``.

    ``title + heading + content`` — no field weighting, per the BM25 contract.
    """
    return "\n".join(part for part in (chunk.title, chunk.heading, chunk.content) if part)


@dataclass(frozen=True)
class BM25TermContribution:
    """Per-term explanation of a chunk's BM25 score."""

    term: str
    document_frequency: int
    idf: float
    term_frequency: int
    contribution: float


@dataclass(frozen=True)
class BM25Explanation:
    """Full, auditable explanation of one chunk's BM25 score."""

    chunk_id: str
    score: float
    terms: tuple[BM25TermContribution, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable explanation with deterministic key order."""
        return {
            "chunk_id": self.chunk_id,
            "score": self.score,
            "terms": [
                {
                    "term": t.term,
                    "df": t.document_frequency,
                    "idf": round(t.idf, 6),
                    "tf": t.term_frequency,
                    "contribution": round(t.contribution, 6),
                }
                for t in self.terms
            ],
        }


@dataclass(frozen=True)
class BM25Hit:
    """One scored chunk in a BM25 ranking."""

    chunk_id: str
    doc_id: str
    score: float
    rank: int
    matched_terms: tuple[str, ...]


class BM25Index:
    """A bounded, pure-Python Okapi BM25 index over Week 9 ``Chunk`` objects.

    The index holds no external state and performs no I/O: it is built from an
    in-memory sequence of chunks, which is what makes it trivially testable with
    hand-computed fixtures.
    """

    def __init__(
        self,
        chunks: Iterable[Chunk],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        if k1 < 0:
            raise ValueError(f"k1 must be non-negative, got {k1}")
        if not 0.0 <= b <= 1.0:
            raise ValueError(f"b must be within [0.0, 1.0], got {b}")

        self._k1 = k1
        self._b = b
        self._tokens: dict[str, tuple[str, ...]] = {}
        self._doc_ids: dict[str, str] = {}
        self._term_frequencies: dict[str, Counter[str]] = {}
        self._document_frequency: Counter[str] = Counter()
        self._lengths: dict[str, int] = {}

        # Deterministic internal order: chunk_id ascending, independent of the
        # order in which chunks were ingested.
        for chunk in sorted(chunks, key=lambda c: c.chunk_id):
            tokens = tuple(tokenize(index_text(chunk)))
            self._tokens[chunk.chunk_id] = tokens
            self._doc_ids[chunk.chunk_id] = chunk.doc_id
            self._term_frequencies[chunk.chunk_id] = Counter(tokens)
            self._lengths[chunk.chunk_id] = len(tokens)
            for term in self._term_frequencies[chunk.chunk_id]:
                self._document_frequency[term] += 1

        self._chunk_ids: tuple[str, ...] = tuple(self._tokens)
        self._chunk_count = len(self._chunk_ids)
        self._total_length = sum(self._lengths[cid] for cid in self._chunk_ids)
        self._average_length = (
            self._total_length / self._chunk_count if self._chunk_count else 0.0
        )

    # ------------------------------------------------------------------ metadata

    @property
    def k1(self) -> float:
        """Term-frequency saturation parameter."""
        return self._k1

    @property
    def b(self) -> float:
        """Length-normalization parameter."""
        return self._b

    @property
    def chunk_count(self) -> int:
        """Number of indexed chunks (``N`` in the BM25 formula)."""
        return self._chunk_count

    @property
    def document_count(self) -> int:
        """Number of distinct parent documents in the index."""
        return len(set(self._doc_ids.values()))

    @property
    def average_length(self) -> float:
        """Average token count per chunk (``avgdl``)."""
        return self._average_length

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        """Indexed chunk IDs in deterministic (ascending) order."""
        return self._chunk_ids

    def document_frequency(self, term: str) -> int:
        """Number of indexed chunks containing ``term``."""
        return self._document_frequency.get(term, 0)

    def idf(self, term: str) -> float:
        """Nonnegative smoothed IDF for ``term``."""
        return self._idf(self.document_frequency(term))

    def document_id(self, chunk_id: str) -> str:
        """Parent document ID of ``chunk_id``."""
        return self._doc_ids[chunk_id]

    # ------------------------------------------------------------------- scoring

    def _idf(self, df: int) -> float:
        if self._chunk_count == 0:
            return 0.0
        return math.log(
            1.0 + (self._chunk_count - df + 0.5) / (df + 0.5)
        )

    def _length_normalization(self, chunk_id: str) -> float:
        if self._average_length <= 0.0:
            return 0.0
        length = self._lengths[chunk_id]
        return 1.0 - self._b + self._b * (length / self._average_length)

    def _term_contribution(self, term: str, tf: int, chunk_id: str) -> float:
        idf = self._idf(self._document_frequency.get(term, 0))
        numerator = tf * (self._k1 + 1.0)
        denominator = tf + self._k1 * self._length_normalization(chunk_id)
        if denominator <= 0.0:
            return 0.0
        return idf * (numerator / denominator)

    def score(self, query: str, chunk_id: str) -> float:
        """BM25 score of ``chunk_id`` for ``query`` (0.0 when no term matches)."""
        if chunk_id not in self._tokens:
            raise KeyError(f"Unknown chunk_id: {chunk_id}")
        total = 0.0
        frequencies = self._term_frequencies[chunk_id]
        for term in unique_tokens(query):
            tf = frequencies.get(term, 0)
            if tf:
                total += self._term_contribution(term, tf, chunk_id)
        return total

    def explain(self, query: str, chunk_id: str) -> BM25Explanation:
        """Return the per-term breakdown whose contributions sum to the score."""
        if chunk_id not in self._tokens:
            raise KeyError(f"Unknown chunk_id: {chunk_id}")

        frequencies = self._term_frequencies[chunk_id]
        terms: list[BM25TermContribution] = []
        total = 0.0
        for term in unique_tokens(query):
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            df = self._document_frequency.get(term, 0)
            contribution = self._term_contribution(term, tf, chunk_id)
            total += contribution
            terms.append(
                BM25TermContribution(
                    term=term,
                    document_frequency=df,
                    idf=self._idf(df),
                    term_frequency=tf,
                    contribution=contribution,
                )
            )
        return BM25Explanation(chunk_id=chunk_id, score=total, terms=tuple(terms))

    def search(self, query: str, top_k: int = 20) -> list[BM25Hit]:
        """Return the top ``top_k`` positively scoring chunks, best first.

        Ordering is score descending, then ``chunk_id`` ascending, so equal scores
        never depend on insertion order. A query that produces no tokens (empty or
        punctuation-only) returns no results.
        """
        if top_k <= 0:
            return []

        query_terms = unique_tokens(query)
        if not query_terms:
            return []

        scored: list[tuple[str, float, tuple[str, ...]]] = []
        for chunk_id in self._chunk_ids:  # deterministic iteration order
            frequencies = self._term_frequencies[chunk_id]
            score = 0.0
            matched: list[str] = []
            for term in query_terms:
                tf = frequencies.get(term, 0)
                if not tf:
                    continue
                score += self._term_contribution(term, tf, chunk_id)
                matched.append(term)
            if score > 0.0:
                scored.append((chunk_id, score, tuple(matched)))

        scored.sort(key=lambda item: (-item[1], item[0]))

        return [
            BM25Hit(
                chunk_id=chunk_id,
                doc_id=self._doc_ids[chunk_id],
                score=score,
                rank=rank,
                matched_terms=matched,
            )
            for rank, (chunk_id, score, matched) in enumerate(scored[:top_k], start=1)
        ]

    def rank_chunk_ids(self, query: str, depth: int) -> list[tuple[str, str]]:
        """Return ``(chunk_id, doc_id)`` pairs for the top ``depth`` BM25 chunks."""
        return [(hit.chunk_id, hit.doc_id) for hit in self.search(query, top_k=depth)]

    def tokens_for(self, chunk_id: str) -> Sequence[str]:
        """Return the indexed token sequence for ``chunk_id``."""
        if chunk_id not in self._tokens:
            raise KeyError(f"Unknown chunk_id: {chunk_id}")
        return self._tokens[chunk_id]
