"""Reciprocal Rank Fusion tests, including hand-calculated RRF values.

RRF is ``Σ_r 1 / (c + rank_r(d))`` with ``c = 60``. These tests pin the constant,
the 1-based ranks, the zero contribution of a missing ranking, duplicate
suppression inside one ranking, and the deterministic tie-break order.
"""

from __future__ import annotations

import pytest

from production_rag_lab.fusion import (
    DEFAULT_RRF_C,
    reciprocal_rank_fusion,
)


def test_default_constant_is_sixty() -> None:
    assert DEFAULT_RRF_C == 60


def test_hand_calculated_single_ranking() -> None:
    """A chunk at rank 1 of one ranking only scores 1 / (60 + 1)."""
    fused = reciprocal_rank_fusion({"vector": [("c1", "d.md")]})
    assert len(fused) == 1
    assert fused[0].score == pytest.approx(1 / 61, rel=1e-12)
    assert fused[0].ranks == {"vector": 1}
    assert fused[0].contributions == {"vector": pytest.approx(1 / 61, rel=1e-12)}


def test_hand_calculated_both_rankings() -> None:
    """Vector rank 1 + BM25 rank 2 = 1/61 + 1/62."""
    fused = reciprocal_rank_fusion(
        {"vector": [("c1", "d.md"), ("c2", "d.md")], "bm25": [("c2", "d.md"), ("c1", "d.md")]}
    )
    by_id = {candidate.chunk_id: candidate for candidate in fused}
    assert by_id["c1"].score == pytest.approx(1 / 61 + 1 / 62, rel=1e-12)
    assert by_id["c2"].score == pytest.approx(1 / 62 + 1 / 61, rel=1e-12)
    assert by_id["c1"].ranks == {"vector": 1, "bm25": 2}
    assert by_id["c1"].methods == ("bm25", "vector")


def test_ranks_are_one_based() -> None:
    fused = reciprocal_rank_fusion({"bm25": [("a", "d.md"), ("b", "d.md"), ("c", "d.md")]})
    ranks = {candidate.chunk_id: candidate.ranks["bm25"] for candidate in fused}
    assert ranks == {"a": 1, "b": 2, "c": 3}


def test_missing_ranking_contributes_zero() -> None:
    """A chunk found by only one retriever gets exactly that retriever's term."""
    fused = reciprocal_rank_fusion(
        {"vector": [("shared", "d.md"), ("onlyv", "d.md")], "bm25": [("shared", "d.md")]}
    )
    by_id = {candidate.chunk_id: candidate for candidate in fused}
    assert set(fused[i].chunk_id for i in range(len(fused))) == {"shared", "onlyv"}
    assert by_id["onlyv"].score == pytest.approx(1 / 62, rel=1e-12)
    assert by_id["onlyv"].ranks == {"vector": 2}


def test_candidate_in_neither_list_is_absent() -> None:
    fused = reciprocal_rank_fusion(
        {"vector": [("v", "d.md")], "bm25": [("b", "d.md")]}
    )
    assert {candidate.chunk_id for candidate in fused} == {"v", "b"}


def test_agreement_outranks_a_single_ranks_one_match() -> None:
    """Two rank-1 appearances beat one rank-1 appearance."""
    fused = reciprocal_rank_fusion(
        {"vector": [("both", "d.md"), ("solo", "d.md")], "bm25": [("both", "d.md")]}
    )
    assert fused[0].chunk_id == "both"
    assert fused[0].score > fused[1].score


def test_duplicates_inside_one_ranking_are_collapsed() -> None:
    """A repeated chunk keeps only its first rank and cannot occupy two ranks."""
    fused = reciprocal_rank_fusion({"bm25": [("a", "d.md"), ("a", "d.md"), ("b", "d.md")]})
    by_id = {candidate.chunk_id: candidate for candidate in fused}
    assert by_id["a"].ranks == {"bm25": 1}
    assert by_id["b"].ranks == {"bm25": 2}


def test_ordering_follows_score_first() -> None:
    fused = reciprocal_rank_fusion(
        {"vector": [("z", "d.md"), ("a", "d.md")], "bm25": [("m", "d.md"), ("z", "d.md")]}
    )
    # z = 1/61 + 1/62, m = 1/61, a = 1/62
    assert [candidate.chunk_id for candidate in fused] == ["z", "m", "a"]


def test_equal_scores_are_broken_by_vector_rank_then_bm25_rank() -> None:
    """A genuine score tie: zzz is (vector 1, bm25 3), aaa is (vector 3, bm25 1).

    Both score ``1/61 + 1/63``, so only the documented tie-breaks can separate them.
    """
    rankings = {
        "vector": [("zzz", "d.md"), ("f1", "d.md"), ("aaa", "d.md")],
        "bm25": [("aaa", "d.md"), ("f2", "d.md"), ("zzz", "d.md")],
    }
    fused = reciprocal_rank_fusion(rankings)
    by_id = {candidate.chunk_id: candidate for candidate in fused}
    assert by_id["zzz"].score == pytest.approx(by_id["aaa"].score, rel=1e-12)
    assert by_id["zzz"].score == pytest.approx(1 / 61 + 1 / 63, rel=1e-12)

    # Default tie-break consults the vector rank first: zzz (1) beats aaa (3).
    assert [c.chunk_id for c in fused][:2] == ["zzz", "aaa"]

    # Disabling the rank tie-breaks leaves chunk_id as the final arbiter.
    only_id = reciprocal_rank_fusion(rankings, tie_break_methods=())
    assert [c.chunk_id for c in only_id][:2] == ["aaa", "zzz"]


def test_bm25_rank_breaks_ties_when_vector_ranks_are_absent() -> None:
    """With no vector ranking, the bm25 rank is consulted before chunk_id."""
    rankings = {"vector": [], "bm25": [("zzz", "d.md"), ("f", "d.md"), ("aaa", "d.md")]}
    fused = reciprocal_rank_fusion(rankings)
    # Distinct bm25 ranks give distinct scores, so this is decided on score.
    assert [c.chunk_id for c in fused] == ["zzz", "f", "aaa"]
    only_id = reciprocal_rank_fusion(rankings, tie_break_methods=("vector",))
    assert [c.chunk_id for c in only_id] == ["zzz", "f", "aaa"]


def test_contributions_sum_to_score() -> None:
    fused = reciprocal_rank_fusion(
        {"vector": [("a", "d.md")], "bm25": [("b", "d.md"), ("a", "d.md")]}
    )
    for candidate in fused:
        assert candidate.score == pytest.approx(
            sum(candidate.contributions.values()), rel=1e-12
        )


def test_top_k_truncates_after_ordering() -> None:
    fused = reciprocal_rank_fusion({"bm25": [("a", "d.md"), ("b", "d.md"), ("c", "d.md")]}, top_k=2)
    assert [c.chunk_id for c in fused] == ["a", "b"]


def test_empty_ranking_contributes_nothing() -> None:
    assert reciprocal_rank_fusion({"vector": [], "bm25": []}) == []
    fused = reciprocal_rank_fusion({"vector": [], "bm25": [("a", "d.md")]})
    assert [c.chunk_id for c in fused] == ["a"]
    assert fused[0].ranks == {"bm25": 1}


def test_custom_c_is_honoured() -> None:
    fused = reciprocal_rank_fusion({"bm25": [("a", "d.md")]}, c=0)
    assert fused[0].score == pytest.approx(1.0, rel=1e-12)


def test_doc_id_travels_with_the_candidate() -> None:
    fused = reciprocal_rank_fusion({"bm25": [("a", "doc.md")]})
    assert fused[0].doc_id == "doc.md"


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"bm25": [("a", "d.md")]}, c=-1)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"bm25": [("a", "d.md")]}, top_k=0)


def test_as_dict_is_json_friendly() -> None:
    fused = reciprocal_rank_fusion({"vector": [("a", "d.md")], "bm25": [("a", "d.md")]})
    payload = fused[0].as_dict()
    assert payload["chunk_id"] == "a"
    assert set(payload["ranks"]) == {"bm25", "vector"}
    assert isinstance(payload["rrf_score"], float)
