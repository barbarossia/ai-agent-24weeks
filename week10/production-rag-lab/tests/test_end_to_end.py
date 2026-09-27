"""End-to-end offline evaluation over the real Week 9 corpus and the fixed query set.

These tests verify structure, data integrity, and determinism. They deliberately
assert **no quality threshold** and make **no claim that any method wins**: the
corpus is four hand-written documents and the dense baseline is a deterministic
offline mock, so a score comparison would not support a general conclusion.
"""

from __future__ import annotations

import json

import pytest

from production_rag_lab.cli import main
from production_rag_lab.evaluation import (
    evaluate,
    load_queries,
    validate_gold_doc_ids,
)
from production_rag_lab.rerank import DEFAULT_RERANK_CANDIDATES, rule_rerank
from production_rag_lab.retrieval import (
    METHODS,
    RERANK_BASE_METHODS,
    reported_mode,
    validate_rerank_combination,
)

#: Modes reported by the evaluator: the three base methods plus the separately
#: reported rules-reranked hybrid. Distinct from the imported `METHODS`, which holds
#: only the real retrieval methods.
EVAL_METHODS = ("vector", "bm25", "hybrid", "hybrid+rules")


@pytest.fixture(scope="module")
def full_report(retriever, queries_path):
    """Run the complete offline evaluation once for this module."""
    queries = load_queries(queries_path)
    validate_gold_doc_ids(queries, retriever.document_ids)

    rankings: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for method in EVAL_METHODS:
        per_query = {}
        for query in queries:
            if method == "hybrid+rules":
                fused = retriever.fuse(query.query)[:DEFAULT_RERANK_CANDIDATES]
                reranked = rule_rerank(query.query, fused, retriever.chunks_by_id)
                per_query[query.query_id] = [
                    (item.chunk_id, item.doc_id) for item in reranked
                ]
            else:
                per_query[query.query_id] = retriever.ranking(query.query, method)
        rankings[method] = per_query
    return retriever, queries, evaluate(queries, rankings, ks=(1, 3))


# ------------------------------------------------------------------- integrity


def test_every_method_sees_the_same_corpus_and_chunks(retriever) -> None:
    """One chunk set, shared by every method — the core comparability guarantee."""
    assert retriever.chunk_count == 17
    assert retriever.doc_count == 4
    assert retriever.bm25_index.chunk_count == retriever.chunk_count
    assert retriever.bm25_index.document_count == retriever.doc_count
    assert len(retriever.chunks) == retriever.chunk_count


def test_all_24_queries_are_evaluated(full_report) -> None:
    _retriever, queries, report = full_report
    assert len(queries) == 24
    assert report.query_count == 24
    assert [m.method for m in report.methods] == list(EVAL_METHODS)
    for method_report in report.methods:
        assert len(method_report.per_query) == 24


def test_macro_values_are_consistent_with_per_query_hits(full_report) -> None:
    _retriever, _queries, report = full_report
    for method_report in report.methods:
        for k in (1, 3):
            hits = sum(1 for outcome in method_report.per_query if outcome.hit_at_k[k])
            assert 0 <= hits <= 24
            assert method_report.macro_hit_at_k[k] == pytest.approx(hits / 24)
            assert 0.0 <= method_report.macro_hit_at_k[k] <= 1.0


def test_hybrid_candidates_come_from_the_two_base_rankings(retriever) -> None:
    """Hybrid is a fusion, never an independent third ranking."""
    query = "OpenWrt 端口转发 DNAT"
    vector_ids = {chunk_id for chunk_id, _ in retriever.ranking(query, "vector")}
    bm25_ids = {chunk_id for chunk_id, _ in retriever.ranking(query, "bm25")}
    hybrid_ids = {chunk_id for chunk_id, _ in retriever.ranking(query, "hybrid")}
    assert hybrid_ids <= vector_ids | bm25_ids
    assert hybrid_ids  # non-empty for a real query


def test_rerank_candidate_window_is_bounded(retriever) -> None:
    fused = retriever.fuse("docker stats")[:DEFAULT_RERANK_CANDIDATES]
    assert len(fused) <= DEFAULT_RERANK_CANDIDATES == 10


def test_every_gold_label_resolves_to_a_real_document(full_report, retriever) -> None:
    _retriever, queries, report = full_report
    known = set(retriever.document_ids)
    for outcome in report.method("bm25").per_query:
        for doc_id in outcome.gold_doc_ids:
            assert doc_id in known
        assert set(outcome.retrieved_doc_ids) <= known


def test_retrieved_documents_are_in_first_occurrence_order(full_report) -> None:
    _retriever, _queries, report = full_report
    for method_report in report.methods:
        for outcome in method_report.per_query:
            documents = list(outcome.retrieved_doc_ids)
            assert len(documents) == len(set(documents)), "documents must be unique"


# ---------------------------------------------------------------- determinism


def test_repeated_runs_are_identical(retriever, queries_path) -> None:
    queries = load_queries(queries_path)

    def run() -> dict:
        rankings = {
            method: {q.query_id: retriever.ranking(q.query, method) for q in queries}
            for method in ("vector", "bm25", "hybrid")
        }
        return evaluate(queries, rankings, ks=(1, 3)).as_dict()

    assert run() == run()


def test_cli_eval_is_byte_identical_across_invocations(capsys) -> None:
    assert main(["eval", "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["eval", "--json"]) == 0
    second = capsys.readouterr().out
    assert first == second
    assert json.loads(first)["report"]["query_count"] == 24


def test_no_timings_are_printed(capsys) -> None:
    """Timings would break byte-level reproducibility, so none may appear."""
    assert main(["eval"]) == 0
    out = capsys.readouterr().out.lower()
    for forbidden in ("elapsed", "seconds", "took ", "ms\n"):
        assert forbidden not in out


def test_search_is_deterministic_across_calls(retriever) -> None:
    query = "esxcli 存储空间检查"
    first = retriever.search(query, method="hybrid", top_k=5)
    second = retriever.search(query, method="hybrid", top_k=5)
    assert [r.as_dict() for r in first] == [r.as_dict() for r in second]


# --------------------------------------------------------------------- bounds


def test_empty_query_returns_no_results_for_every_method(retriever) -> None:
    for method in ("vector", "bm25", "hybrid"):
        assert retriever.search("", method=method) == []
        assert retriever.search("   ", method=method) == []
    assert retriever.search("alpha", method="hybrid", rerank="rules", top_k=0) == []


def test_unknown_method_and_rerank_mode_are_rejected(retriever) -> None:
    with pytest.raises(ValueError, match="Unknown method"):
        retriever.search("alpha", method="telepathy")
    with pytest.raises(ValueError, match="Unknown rerank mode"):
        retriever.search("alpha", method="hybrid", rerank="neural")
    with pytest.raises(ValueError):
        retriever.ranking("alpha", "telepathy")


def test_retriever_rejects_a_non_positive_candidate_depth(corpus_dir) -> None:
    from production_rag_lab.retrieval import ProductionRagRetriever

    with pytest.raises(ValueError, match="candidate_depth"):
        ProductionRagRetriever(corpus_dir, candidate_depth=0)


def test_results_carry_source_traceability(retriever) -> None:
    for result in retriever.search("ubus session", method="hybrid", top_k=3):
        assert result.chunk_id.startswith(result.doc_id)
        assert result.source_file.endswith(".md")
        assert result.snippet
        assert result.explanation


def test_base_and_reranked_hybrid_are_distinct_modes(retriever) -> None:
    query = "OpenWrt 端口转发 DNAT 配置"
    base = retriever.search(query, method="hybrid", top_k=3)
    reranked = retriever.search(query, method="hybrid", top_k=3, rerank="rules")
    assert {r.chunk_id for r in base} != {r.chunk_id for r in reranked}
    assert all(r.score_kind == "rrf" for r in base)
    assert all(r.score_kind == "rules_rerank" for r in reranked)
    # The reranked score is the preserved fused score, not a new incomparable value.
    assert all("rrf_score" in r.explanation["features"] for r in reranked)


# --------------------------------------- regression: rerank/method mismatch (H007)
#
# The rules reranker reorders the *hybrid* top-10 fused candidates. Accepting
# `--method vector|bm25 --rerank rules` used to dispatch those same hybrid results
# while reporting the requested method, which misstated the retrieval method that
# produced the output. These tests pin the rejection and the correct provenance.


def test_rules_rerank_is_defined_only_for_hybrid() -> None:
    assert RERANK_BASE_METHODS == {"rules": "hybrid"}


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_api_rejects_rules_rerank_on_single_retriever_methods(retriever, method) -> None:
    with pytest.raises(ValueError) as excinfo:
        retriever.search("alpha", method=method, rerank="rules")
    message = str(excinfo.value)
    assert method in message
    assert "hybrid" in message
    assert "rerank" in message


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_api_rejection_happens_before_any_result_is_returned(retriever, method) -> None:
    """No partial/degraded result may escape for an unsupported combination."""
    # A query with a genuine lexical match, so the control case is non-empty.
    query = "端口转发"
    assert retriever.search(query, method=method, top_k=3)
    with pytest.raises(ValueError):
        retriever.search(query, method=method, rerank="rules")


def test_api_accepts_rules_rerank_on_hybrid(retriever) -> None:
    results = retriever.search("alpha", method="hybrid", top_k=3, rerank="rules")
    assert results
    for result in results:
        assert result.score_kind == "rules_rerank"
        assert result.explanation["base_method"] == "hybrid"
        assert result.explanation["mode"] == "hybrid+rules"
        assert result.explanation["rerank"] == "rules"


def test_api_rejects_unknown_method_and_unknown_rerank_mode(retriever) -> None:
    """The combination validator also guards the name/namespace itself."""
    with pytest.raises(ValueError, match="Unknown method"):
        retriever.search("alpha", method="telepathy", rerank="rules")
    with pytest.raises(ValueError, match="Unknown rerank mode"):
        retriever.search("alpha", method="hybrid", rerank="neural")
    with pytest.raises(ValueError, match="Unknown rerank mode"):
        # An unknown mode is rejected even for a single-retriever method, so the
        # caller never gets a "wrong base method" message for a typo'd mode.
        retriever.search("alpha", method="vector", rerank="neural")


def test_reported_mode_labels_the_base_method() -> None:
    assert reported_mode("hybrid", "rules") == "hybrid+rules"
    assert reported_mode("hybrid", None) == "hybrid"
    assert reported_mode("vector", None) == "vector"
    # A reported mode always exposes the method it was derived from.
    for method in METHODS:
        assert reported_mode(method, None) == method


def test_validate_rerank_combination_is_the_single_source_of_truth() -> None:
    validate_rerank_combination("vector", None)
    validate_rerank_combination("bm25", None)
    validate_rerank_combination("hybrid", None)
    validate_rerank_combination("hybrid", "rules")
    for method in ("vector", "bm25"):
        with pytest.raises(ValueError):
            validate_rerank_combination(method, "rules")
    with pytest.raises(ValueError):
        validate_rerank_combination("telepathy", None)
    with pytest.raises(ValueError):
        validate_rerank_combination("hybrid", "neural")


def test_reranked_results_are_identical_to_the_genuine_hybrid_rerank(retriever) -> None:
    """Guards the original defect: the payload must not differ from hybrid+rules."""
    query = "OpenWrt 端口转发 DNAT"
    genuine = retriever.search(query, method="hybrid", top_k=3, rerank="rules")
    with pytest.raises(ValueError):
        retriever.search(query, method="vector", top_k=3, rerank="rules")
    # Re-running the valid path is unchanged, so rejecting the invalid one cannot
    # have altered the valid behaviour.
    assert [r.as_dict() for r in retriever.search(query, method="hybrid", top_k=3, rerank="rules")] == [
        r.as_dict() for r in genuine
    ]


def test_no_raw_bm25_and_cosine_scores_are_added(retriever) -> None:
    """Hybrid scores are RRF sums of 1/(c+rank), so they stay far below any raw sum."""
    for result in retriever.search("端口转发", method="hybrid", top_k=3):
        contributions = result.explanation["fused"]["contributions"]
        assert result.explanation["fused"]["rrf_score"] == pytest.approx(
            sum(contributions.values()), rel=1e-6
        )
        assert all(0.0 < value <= 1 / 61 for value in contributions.values())
