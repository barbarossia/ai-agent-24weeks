"""BM25 contract tests: the formula, length normalization, IDF, and determinism.

The reference implementation inside this module is an independent, literal
transcription of the formula documented in ``production_rag_lab.lexical``. The
tests therefore check the implementation against the *contract*, not against
itself, and additionally pin a few hand-computed constants.
"""

from __future__ import annotations

import math

import pytest

from production_rag_lab.lexical import DEFAULT_B, DEFAULT_K1, BM25Index

from conftest import make_chunk

K1 = DEFAULT_K1
B = DEFAULT_B


@pytest.fixture()
def index() -> BM25Index:
    """A three-chunk, hand-controlled corpus with a known average length.

    ``avgdl = (3 + 2 + 3) / 3 = 8/3``; ``alpha``/``beta``/``gamma`` have df 2 and
    ``delta`` has df 1.
    """
    chunks = [
        make_chunk("c1", "doc1.md", "alpha alpha beta"),
        make_chunk("c2", "doc2.md", "alpha gamma"),
        make_chunk("c3", "doc3.md", "beta gamma delta"),
    ]
    return BM25Index(chunks, k1=K1, b=B)


def reference_idf(n: int, df: int) -> float:
    """Nonnegative smoothed IDF exactly as written in the module docstring."""
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


def reference_contribution(n: int, df: int, tf: int, length: int, avgdl: float) -> float:
    """One term's contribution to the BM25 score."""
    numerator = tf * (K1 + 1.0)
    denominator = tf + K1 * (1.0 - B + B * (length / avgdl))
    return reference_idf(n, df) * (numerator / denominator)


# ------------------------------------------------------------------- hand values


def test_hand_computed_idf_values(index: BM25Index) -> None:
    # ln(1 + (3-2+0.5)/(2+0.5)) and ln(1 + (3-1+0.5)/(1+0.5))
    assert index.idf("alpha") == pytest.approx(0.47000362924573563, rel=1e-12)
    assert index.idf("delta") == pytest.approx(0.9808292530117263, rel=1e-12)


def test_hand_computed_scores(index: BM25Index) -> None:
    # c1: tf(alpha)=2, |d|=3 -> idf * 5 / (2 + 1.5 * 1.09375)
    assert index.score("alpha", "c1") == pytest.approx(0.6454985466035854, rel=1e-12)
    # c2: tf(alpha)=1, |d|=2
    assert index.score("alpha", "c2") == pytest.approx(0.5295815540797021, rel=1e-12)
    # c3: only 'delta' matches, tf=1, |d|=3
    assert index.score("delta", "c3") == pytest.approx(0.9285957424963089, rel=1e-12)


def test_average_length_and_counts(index: BM25Index) -> None:
    assert index.chunk_count == 3
    assert index.document_count == 3
    assert index.average_length == pytest.approx(8 / 3, rel=1e-12)
    assert index.document_frequency("alpha") == 2
    assert index.document_frequency("delta") == 1
    assert index.document_frequency("absent") == 0


# ------------------------------------------------------------ formula agreement


@pytest.mark.parametrize(
    ("query", "chunk_id", "tf", "length", "df"),
    [
        ("alpha", "c1", 2, 3, 2),
        ("alpha", "c2", 1, 2, 2),
        ("beta", "c1", 1, 3, 2),
        ("gamma", "c2", 1, 2, 2),
        ("delta", "c3", 1, 3, 1),
    ],
)
def test_score_matches_reference_formula(
    index: BM25Index, query: str, chunk_id: str, tf: int, length: int, df: int
) -> None:
    expected = reference_contribution(
        n=3, df=df, tf=tf, length=length, avgdl=index.average_length
    )
    assert index.score(query, chunk_id) == pytest.approx(expected, rel=1e-12)


def test_multi_term_score_is_the_sum_of_term_contributions(index: BM25Index) -> None:
    expected = reference_contribution(3, 2, 1, 3, index.average_length) + reference_contribution(
        3, 2, 1, 3, index.average_length
    )  # 'beta' and 'gamma' both have df 2, tf 1, |d| 3 in c3
    assert index.score("beta gamma", "c3") == pytest.approx(expected, rel=1e-12)


def _same_tf_index(b: float) -> BM25Index:
    """Two chunks with tf(alpha)=1 each but different lengths (1 vs 4 tokens)."""
    return BM25Index(
        [
            make_chunk("s", "doc1.md", "alpha"),
            make_chunk("l", "doc2.md", "alpha beta gamma delta"),
        ],
        b=b,
    )


def test_length_normalization_penalizes_longer_chunks() -> None:
    """Same tf and same idf: only length normalization can separate the two."""
    index = _same_tf_index(b=0.75)
    assert index.score("alpha", "s") > index.score("alpha", "l")


def test_b_zero_disables_length_normalization() -> None:
    index = _same_tf_index(b=0.0)
    assert index.score("alpha", "s") == pytest.approx(index.score("alpha", "l"), rel=1e-12)


def test_smoothed_idf_is_always_positive_for_indexed_terms() -> None:
    """Even a term present in every chunk keeps a positive IDF here."""
    chunks = [make_chunk(f"c{i}", "d.md", "alpha") for i in range(4)]
    index = BM25Index(chunks)
    assert index.idf("alpha") > 0.0


# ------------------------------------------------------------------- behaviour


def test_repeated_query_term_does_not_multiply_weight(index: BM25Index) -> None:
    assert index.score("alpha alpha alpha", "c1") == pytest.approx(
        index.score("alpha", "c1"), rel=1e-12
    )


def test_zero_match_query_returns_no_results(index: BM25Index) -> None:
    assert index.search("nonexistentterm") == []
    assert index.score("nonexistentterm", "c1") == 0.0


def test_empty_or_punctuation_query_returns_no_results(index: BM25Index) -> None:
    for query in ("", "   ", "...", "---"):
        assert index.search(query) == []


def test_search_orders_by_score_then_chunk_id(index: BM25Index) -> None:
    hits = index.search("alpha", top_k=3)
    assert [hit.chunk_id for hit in hits] == ["c1", "c2"]
    assert [hit.rank for hit in hits] == [1, 2]
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)


def test_equal_scores_break_ties_by_chunk_id() -> None:
    """Identical text under two chunk IDs must always order by chunk ID."""
    chunks = [
        make_chunk("zzz", "doc2.md", "alpha"),
        make_chunk("aaa", "doc1.md", "alpha"),
    ]
    index = BM25Index(chunks)
    hits = index.search("alpha", top_k=2)
    assert [hit.chunk_id for hit in hits] == ["aaa", "zzz"]
    assert hits[0].score == pytest.approx(hits[1].score, rel=1e-12)


def test_index_order_does_not_affect_results() -> None:
    chunks = [
        make_chunk("c1", "doc1.md", "alpha alpha beta"),
        make_chunk("c2", "doc2.md", "alpha gamma"),
        make_chunk("c3", "doc3.md", "beta gamma delta"),
    ]
    forward = BM25Index(chunks).search("beta gamma", top_k=3)
    backward = BM25Index(list(reversed(chunks))).search("beta gamma", top_k=3)
    assert [(h.chunk_id, h.score) for h in forward] == [(h.chunk_id, h.score) for h in backward]


def test_top_k_truncates_and_ranks_from_one(index: BM25Index) -> None:
    hits = index.search("alpha beta gamma delta", top_k=1)
    assert len(hits) == 1
    assert hits[0].rank == 1
    assert index.search("alpha", top_k=0) == []


def test_matched_terms_are_reported(index: BM25Index) -> None:
    hits = index.search("alpha beta", top_k=3)
    assert hits[0].chunk_id == "c1"
    assert set(hits[0].matched_terms) == {"alpha", "beta"}


def test_explanation_sums_to_score(index: BM25Index) -> None:
    explanation = index.explain("alpha beta", "c1")
    assert explanation.chunk_id == "c1"
    assert [t.term for t in explanation.terms] == ["alpha", "beta"]
    assert sum(t.contribution for t in explanation.terms) == pytest.approx(
        explanation.score, rel=1e-12
    )
    assert explanation.score == pytest.approx(index.score("alpha beta", "c1"), rel=1e-12)
    assert explanation.as_dict()["terms"][0]["term"] == "alpha"


def test_explanation_of_unmatched_chunk_is_empty(index: BM25Index) -> None:
    explanation = index.explain("alpha", "c3")
    # c3 has no 'alpha' token.
    assert explanation.terms == ()
    assert explanation.score == 0.0


def test_unknown_chunk_id_raises(index: BM25Index) -> None:
    with pytest.raises(KeyError):
        index.score("alpha", "nope")
    with pytest.raises(KeyError):
        index.explain("alpha", "nope")
    with pytest.raises(KeyError):
        index.tokens_for("nope")


def test_empty_index_is_safe() -> None:
    index = BM25Index([])
    assert index.chunk_count == 0
    assert index.document_count == 0
    assert index.average_length == 0.0
    assert index.search("alpha") == []
    assert index.idf("alpha") == 0.0


def test_index_over_tokenless_chunks_returns_nothing() -> None:
    index = BM25Index([make_chunk("c1", "d.md", "..."), make_chunk("c2", "d.md", "!!!")])
    assert index.average_length == 0.0
    assert index.search("alpha") == []


def test_invalid_parameters_are_rejected() -> None:
    chunks = [make_chunk("c1", "d.md", "alpha")]
    with pytest.raises(ValueError):
        BM25Index(chunks, k1=-1.0)
    with pytest.raises(ValueError):
        BM25Index(chunks, b=1.5)
    with pytest.raises(ValueError):
        BM25Index(chunks, b=-0.1)


def test_rank_chunk_ids_returns_pairs(index: BM25Index) -> None:
    assert index.rank_chunk_ids("alpha", 3) == [("c1", "doc1.md"), ("c2", "doc2.md")]


def test_tokens_for_returns_indexed_tokens(index: BM25Index) -> None:
    assert list(index.tokens_for("c2")) == ["alpha", "gamma"]


def test_cjk_tokens_contribute_to_scores() -> None:
    """The mixed-language contract must actually match CJK, not just ASCII."""
    index = BM25Index(
        [
            make_chunk("c1", "zh.md", "端口转发配置说明"),
            make_chunk("c2", "en.md", "port forwarding guide"),
        ]
    )
    hits = index.search("端口转发", top_k=5)
    assert [hit.chunk_id for hit in hits] == ["c1"]
    assert "端口" in hits[0].matched_terms and "转发" in hits[0].matched_terms
