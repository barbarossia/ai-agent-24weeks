"""Deterministic rule reranker tests.

The reranker must stay bounded, explainable, a pure permutation of its input, and
free of any quality promise.
"""

from __future__ import annotations

import pytest

from production_rag_lab.fusion import FusedCandidate
from production_rag_lab.rerank import DEFAULT_RERANK_CANDIDATES, rule_rerank

from conftest import make_chunk


def candidate(chunk_id: str, doc_id: str, score: float) -> FusedCandidate:
    return FusedCandidate(
        chunk_id=chunk_id,
        doc_id=doc_id,
        score=score,
        ranks={"vector": 1, "bm25": 1},
        contributions={"vector": score / 2, "bm25": score / 2},
    )


def build_chunks():
    return {
        "c_exact": make_chunk("c_exact", "d.md", "The port forwarding rule for wan to lan"),
        "c_partial": make_chunk("c_partial", "d.md", "A forwarding rule that mentions ports"),
        "c_unrelated": make_chunk("c_unrelated", "d.md", "Snapshot consolidation steps"),
    }


# ------------------------------------------------------------------ ordering


def test_exact_phrase_outranks_otherwise_equal_candidate() -> None:
    chunks = build_chunks()
    ranked = rule_rerank(
        "port forwarding",
        [candidate("c_unrelated", "d.md", 0.05), candidate("c_partial", "d.md", 0.05), candidate("c_exact", "d.md", 0.05)],
        chunks,
    )
    # c_exact contains "port forwarding" verbatim, so the phrase signal wins even
    # though all three candidates share the same RRF score.
    assert ranked[0].chunk_id == "c_exact"
    assert ranked[0].exact_phrase_match is True
    assert [item.chunk_id for item in ranked][1] == "c_partial"
    assert ranked[1].exact_phrase_match is False


def test_distinct_token_count_is_the_second_signal() -> None:
    chunks = {
        "c_one": make_chunk("c_one", "d.md", "alpha only"),
        "c_two": make_chunk("c_two", "d.md", "alpha and beta"),
    }
    ranked = rule_rerank(
        "alpha beta gamma",
        [candidate("c_one", "d.md", 0.9), candidate("c_two", "d.md", 0.1)],
        chunks,
    )
    # c_two matches more distinct query tokens despite a much lower RRF score.
    assert [item.chunk_id for item in ranked] == ["c_two", "c_one"]
    assert ranked[0].matched_token_count == 2
    assert ranked[1].matched_token_count == 1


def test_rrf_score_is_the_third_signal() -> None:
    chunks = {
        "c_high": make_chunk("c_high", "d.md", "alpha"),
        "c_low": make_chunk("c_low", "d.md", "alpha"),
    }
    ranked = rule_rerank(
        "alpha", [candidate("c_low", "d.md", 0.01), candidate("c_high", "d.md", 0.5)], chunks
    )
    assert [item.chunk_id for item in ranked] == ["c_high", "c_low"]


def test_chunk_id_is_the_final_tiebreak() -> None:
    chunks = {
        "b_chunk": make_chunk("b_chunk", "d.md", "alpha"),
        "a_chunk": make_chunk("a_chunk", "d.md", "alpha"),
    }
    ranked = rule_rerank(
        "alpha",
        [candidate("b_chunk", "d.md", 0.2), candidate("a_chunk", "d.md", 0.2)],
        chunks,
    )
    assert [item.chunk_id for item in ranked] == ["a_chunk", "b_chunk"]


def test_cjk_queries_are_matched_with_the_shared_tokenizer() -> None:
    chunks = {"c": make_chunk("c", "d.md", "端口转发与防火墙配置")}
    ranked = rule_rerank("端口转发", [candidate("c", "d.md", 0.1)], chunks)
    # Query "端口转发" yields unigrams 端/口/转/发 and bigrams 端口/口转/转发; the
    # chunk contains a superset of them, so all seven distinct tokens match.
    assert ranked[0].exact_phrase_match is True
    assert set(ranked[0].matched_tokens) == {"端", "口", "转", "发", "端口", "口转", "转发"}
    assert ranked[0].matched_token_count == 7


# -------------------------------------------------------------------- bounds


def test_default_candidate_limit_is_ten() -> None:
    assert DEFAULT_RERANK_CANDIDATES == 10


def test_more_than_ten_candidates_is_rejected() -> None:
    chunks = {f"c{i}": make_chunk(f"c{i}", "d.md", "alpha") for i in range(11)}
    too_many = [candidate(f"c{i}", "d.md", 0.1) for i in range(11)]
    with pytest.raises(ValueError, match="at most 10"):
        rule_rerank("alpha", too_many, chunks)


def test_exactly_ten_candidates_is_accepted() -> None:
    chunks = {f"c{i}": make_chunk(f"c{i}", "d.md", "alpha") for i in range(10)}
    ten = [candidate(f"c{i}", "d.md", 0.1) for i in range(10)]
    assert len(rule_rerank("alpha", ten, chunks)) == 10


def test_invalid_max_candidates_is_rejected() -> None:
    with pytest.raises(ValueError):
        rule_rerank("alpha", [], {}, max_candidates=0)


def test_output_is_a_permutation_of_the_input() -> None:
    chunks = {f"c{i}": make_chunk(f"c{i}", "d.md", f"alpha {i} beta") for i in range(6)}
    incoming = [candidate(f"c{i}", "d.md", 0.30 - i / 100) for i in range(6)]
    # Shuffle the input order to prove the output does not depend on it.
    shuffled = [incoming[3], incoming[0], incoming[5], incoming[1], incoming[4], incoming[2]]
    ranked = rule_rerank("alpha beta", shuffled, chunks)
    assert {item.chunk_id for item in ranked} == {item.chunk_id for item in shuffled}
    assert len(ranked) == len(shuffled)
    assert [item.position for item in ranked] == [1, 2, 3, 4, 5, 6]


def test_no_candidate_outside_the_input_can_appear() -> None:
    chunks = {f"c{i}": make_chunk(f"c{i}", "d.md", "alpha") for i in range(4)}
    ranked = rule_rerank("alpha", [candidate("c0", "d.md", 0.2)], chunks)
    assert [item.chunk_id for item in ranked] == ["c0"]


def test_empty_input_returns_empty_output() -> None:
    assert rule_rerank("alpha", [], {}) == []


def test_deterministic_across_repeated_calls() -> None:
    chunks = {f"c{i}": make_chunk(f"c{i}", "d.md", f"alpha beta {i}") for i in range(5)}
    incoming = [candidate(f"c{i}", "d.md", 0.1 * (i + 1)) for i in range(5)]
    first = rule_rerank("alpha beta", incoming, chunks)
    second = rule_rerank("alpha beta", incoming, chunks)
    assert [i.as_dict() for i in first] == [i.as_dict() for i in second]


# -------------------------------------------------------------- explanation


def test_features_are_recorded_for_explanation() -> None:
    chunks = {"c": make_chunk("c", "d.md", "alpha beta")}
    payload = rule_rerank("alpha beta", [candidate("c", "d.md", 0.42)], chunks)[0].as_dict()
    assert payload["chunk_id"] == "c"
    assert payload["exact_phrase_match"] is True
    assert payload["matched_token_count"] == 2
    assert payload["rrf_score"] == pytest.approx(0.42, rel=1e-12)
    assert payload["matched_tokens"] == ["alpha", "beta"]


def test_custom_chunk_text_extractor_is_used() -> None:
    chunks = {"c": make_chunk("c", "d.md", "no query terms here")}
    ranked = rule_rerank(
        "alpha",
        [candidate("c", "d.md", 0.1)],
        chunks,
        chunk_text=lambda chunk: "alpha alpha beta",
    )
    assert ranked[0].matched_token_count == 1
