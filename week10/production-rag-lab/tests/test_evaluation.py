"""Evaluation tests: gold-label validation and the document-level Hit@k contract.

The most important assertions here are the *document-collapse* ones: they prove
that ``k`` counts unique retrieved documents rather than chunks, which is the
metric contract the task's research review accepted.
"""

from __future__ import annotations

import json

import pytest

from production_rag_lab.evaluation import (
    EXPECTED_QUERY_COUNT,
    EvalDataError,
    EvalQuery,
    check_candidate_depth,
    collapse_to_unique_documents,
    evaluate,
    file_sha256,
    hit_at_k,
    load_queries,
    validate_gold_doc_ids,
)

GOLD_DOCS = (
    "docker_homelab_services.md",
    "esxi_storage_management.md",
    "openwrt_firewall_setup.md",
    "openwrt_ubus_guide.md",
)


def write_jsonl(path, rows) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def valid_row(query_id: str = "q01", gold: list[str] | None = None) -> dict:
    return {
        "query_id": query_id,
        "query": f"question {query_id}",
        "gold_doc_ids": gold if gold is not None else ["openwrt_ubus_guide.md"],
        "notes": "unit test",
    }


# ------------------------------------------------------------ data validation


def test_loads_a_valid_file(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [valid_row("q01"), valid_row("q02", ["docker_homelab_services.md"])])
    queries = load_queries(path)
    assert [q.query_id for q in queries] == ["q01", "q02"]
    assert queries[0].gold_doc_ids == ("openwrt_ubus_guide.md",)
    assert queries[1].query == "question q02"


def test_blank_lines_are_ignored(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(
        json.dumps(valid_row("q01"), ensure_ascii=False) + "\n\n\n"
        + json.dumps(valid_row("q02"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert len(load_queries(path)) == 2


def test_duplicate_gold_ids_are_deduplicated(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [valid_row("q01", ["a.md", "a.md", "b.md"])])
    assert load_queries(path)[0].gold_doc_ids == ("a.md", "b.md")


def test_missing_file_is_rejected(tmp_path) -> None:
    with pytest.raises(EvalDataError, match="not found"):
        load_queries(tmp_path / "nope.jsonl")


def test_empty_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(EvalDataError, match="empty"):
        load_queries(path)


def test_invalid_json_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(EvalDataError, match="invalid JSON"):
        load_queries(path)


def test_non_object_row_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text('["q01"]\n', encoding="utf-8")
    with pytest.raises(EvalDataError, match="expected a JSON object"):
        load_queries(path)


def test_duplicate_query_id_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [valid_row("q01"), valid_row("q01")])
    with pytest.raises(EvalDataError, match="duplicate query_id"):
        load_queries(path)


def test_empty_gold_list_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [valid_row("q01", [])])
    with pytest.raises(EvalDataError, match="non-empty list"):
        load_queries(path)


def test_missing_gold_field_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    row = valid_row("q01")
    del row["gold_doc_ids"]
    write_jsonl(path, [row])
    with pytest.raises(EvalDataError, match="non-empty list"):
        load_queries(path)


def test_blank_query_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    row = valid_row("q01")
    row["query"] = "   "
    write_jsonl(path, [row])
    with pytest.raises(EvalDataError, match="'query'"):
        load_queries(path)


def test_blank_query_id_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    row = valid_row("")
    write_jsonl(path, [row])
    with pytest.raises(EvalDataError, match="'query_id'"):
        load_queries(path)


def test_non_string_gold_entry_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [valid_row("q01", [123])])
    with pytest.raises(EvalDataError, match="gold_doc_ids"):
        load_queries(path)


def test_non_string_notes_is_rejected(tmp_path) -> None:
    path = tmp_path / "queries.jsonl"
    row = valid_row("q01")
    row["notes"] = 5
    write_jsonl(path, [row])
    with pytest.raises(EvalDataError, match="'notes'"):
        load_queries(path)


def test_gold_labels_must_exist_in_the_corpus() -> None:
    queries = [EvalQuery("q01", "q", ("missing.md",), "")]
    with pytest.raises(EvalDataError, match="Unknown gold document ID"):
        validate_gold_doc_ids(queries, GOLD_DOCS)


def test_gold_labels_are_never_silently_remapped() -> None:
    queries = [EvalQuery("q01", "q", ("openwrt_ubus_guide.md", "missing.md"), "")]
    with pytest.raises(EvalDataError, match="missing.md"):
        validate_gold_doc_ids(queries, GOLD_DOCS)


def test_empty_corpus_cannot_validate_labels() -> None:
    with pytest.raises(EvalDataError, match="no documents"):
        validate_gold_doc_ids([EvalQuery("q01", "q", GOLD_DOCS[:1], "")], [])


# --------------------------------------------------------- document collapse


def test_collapse_keeps_first_occurrence_order() -> None:
    ranked = [
        ("a#1", "a.md"),
        ("b#1", "b.md"),
        ("a#2", "a.md"),
        ("c#1", "c.md"),
        ("b#2", "b.md"),
    ]
    assert collapse_to_unique_documents(ranked) == ("a.md", "b.md", "c.md")


def test_collapse_of_empty_ranking_is_empty() -> None:
    assert collapse_to_unique_documents([]) == ()


def test_k_counts_unique_documents_not_chunks() -> None:
    """Four chunks of a non-gold document occupy chunk ranks 1-4, gold is chunk 5.

    Collapsing to unique documents gives ``(a.md, gold.md)``, so the gold document
    sits at unique-document rank 2: Hit@1 must miss and Hit@2 must hit. A
    chunk-level reading of the same list would have needed k=5 to succeed, which is
    exactly the unit confusion the task's research review flagged.
    """
    ranked = [
        ("a#1", "a.md"),
        ("a#2", "a.md"),
        ("a#3", "a.md"),
        ("a#4", "a.md"),
        ("gold#1", "gold.md"),
    ]
    documents = collapse_to_unique_documents(ranked)
    assert documents == ("a.md", "gold.md")
    assert hit_at_k(documents, ["gold.md"], 1) is False
    assert hit_at_k(documents, ["gold.md"], 2) is True
    # The gold chunk itself is at chunk rank 5 of 5.
    assert len(ranked) == 5


def test_a_document_filling_the_window_with_chunks_still_hits_at_one() -> None:
    """Many chunks of the gold document still collapse to a single document hit."""
    ranked = [
        ("gold#1", "gold.md"),
        ("gold#2", "gold.md"),
        ("gold#3", "gold.md"),
        ("gold#4", "gold.md"),
        ("a#1", "a.md"),
    ]
    documents = collapse_to_unique_documents(ranked)
    assert documents == ("gold.md", "a.md")
    assert hit_at_k(documents, ["gold.md"], 1) is True


def test_hit_requires_gold_within_the_cutoff() -> None:
    documents = ("a.md", "b.md", "c.md", "gold.md")
    assert hit_at_k(documents, ["gold.md"], 1) is False
    assert hit_at_k(documents, ["gold.md"], 3) is False
    assert hit_at_k(documents, ["gold.md"], 4) is True


def test_no_results_is_a_miss() -> None:
    assert hit_at_k((), ["gold.md"], 1) is False
    assert hit_at_k((), ["gold.md"], 3) is False


def test_k_beyond_the_list_end_still_evaluates_what_exists() -> None:
    assert hit_at_k(("gold.md",), ["gold.md"], 10) is True
    assert hit_at_k(("a.md",), ["gold.md"], 10) is False


def test_non_positive_cutoff_is_a_miss() -> None:
    assert hit_at_k(("gold.md",), ["gold.md"], 0) is False
    assert hit_at_k(("gold.md",), ["gold.md"], -1) is False


def test_empty_gold_set_is_a_miss() -> None:
    assert hit_at_k(("a.md",), (), 1) is False


def test_any_gold_document_satisfies_the_hit() -> None:
    assert hit_at_k(("a.md", "b.md"), ["zzz.md", "b.md"], 2) is True


# ------------------------------------------------------------------- macro


def make_query(query_id: str, gold: str) -> EvalQuery:
    return EvalQuery(query_id=query_id, query=f"q {query_id}", gold_doc_ids=(gold,), notes="")


def test_macro_average_weights_every_query_equally() -> None:
    queries = [make_query(f"q{i:02d}", "a.md") for i in range(1, 5)]
    rankings = {
        "m": {
            "q01": [("x", "a.md")],  # hit
            "q02": [("x", "b.md")],  # miss
            "q03": [("x", "c.md")],  # miss
            "q04": [("x", "a.md")],  # hit
        }
    }
    report = evaluate(queries, rankings, ks=(1,))
    method = report.method("m")
    assert method.hits(1) == 2
    assert method.macro_hit_at_k[1] == pytest.approx(0.5)


def test_hit_at_1_and_hit_at_3_fixture() -> None:
    queries = [make_query("q01", "b.md")]
    rankings = {
        "m": {"q01": [("a#1", "a.md"), ("b#1", "b.md"), ("c#1", "c.md"), ("d#1", "d.md")]}
    }
    method = evaluate(queries, rankings, ks=(1, 3)).method("m")
    assert method.macro_hit_at_k[1] == 0.0
    assert method.macro_hit_at_k[3] == 1.0


def test_report_exposes_retrieved_documents_in_order() -> None:
    queries = [make_query("q01", "b.md")]
    rankings = {"m": {"q01": [("a#1", "a.md"), ("a#2", "a.md"), ("b#1", "b.md")]}}
    outcome = evaluate(queries, rankings, ks=(1,)).method("m").per_query[0]
    assert outcome.retrieved_doc_ids == ("a.md", "b.md")


def test_methods_keep_their_input_order() -> None:
    queries = [make_query("q01", "a.md")]
    rankings = {
        "vector": {"q01": [("x", "a.md")]},
        "bm25": {"q01": [("x", "a.md")]},
        "hybrid": {"q01": [("x", "a.md")]},
    }
    report = evaluate(queries, rankings, ks=(1,))
    assert [m.method for m in report.methods] == ["vector", "bm25", "hybrid"]


def test_missing_method_ranking_is_an_error() -> None:
    queries = [make_query("q01", "a.md"), make_query("q02", "a.md")]
    rankings = {"m": {"q01": [("x", "a.md")]}}
    with pytest.raises(EvalDataError, match="no ranking for query id"):
        evaluate(queries, rankings, ks=(1,))


def test_invalid_cutoffs_are_rejected() -> None:
    queries = [make_query("q01", "a.md")]
    rankings = {"m": {"q01": [("x", "a.md")]}}
    with pytest.raises(EvalDataError):
        evaluate(queries, rankings, ks=())
    with pytest.raises(EvalDataError):
        evaluate(queries, rankings, ks=(0,))
    with pytest.raises(EvalDataError):
        evaluate(queries, rankings, ks=(-1,))


def test_evaluating_no_queries_is_an_error() -> None:
    with pytest.raises(EvalDataError, match="No queries"):
        evaluate([], {"m": {}}, ks=(1,))


def test_cutoffs_are_sorted_and_deduplicated() -> None:
    queries = [make_query("q01", "a.md")]
    report = evaluate(queries, {"m": {"q01": [("x", "a.md")]}}, ks=(3, 1, 3))
    assert report.ks == (1, 3)


def test_unknown_method_lookup_raises() -> None:
    queries = [make_query("q01", "a.md")]
    report = evaluate(queries, {"m": {"q01": [("x", "a.md")]}}, ks=(1,))
    with pytest.raises(KeyError):
        report.method("nope")


def test_as_dict_is_deterministic() -> None:
    queries = [make_query("q01", "a.md")]
    report = evaluate(queries, {"m": {"q01": [("x", "a.md")]}}, ks=(1, 3))
    assert report.as_dict() == report.as_dict()
    assert report.as_dict()["methods"][0]["macro_hit_at_k"] == {"1": 1.0, "3": 1.0}


# --------------------------------------------------------- candidate depth


def test_exhausted_ranking_is_accepted() -> None:
    """Fewer candidates than the cap means nothing was withheld: a miss is honest."""
    check_candidate_depth(
        "bm25",
        "q01",
        candidate_count=2,
        unique_doc_count=2,
        ks=(1, 3),
        candidate_cap=20,
        corpus_chunk_count=17,
        corpus_doc_count=4,
    )


def test_truncated_ranking_without_enough_documents_is_an_error() -> None:
    with pytest.raises(EvalDataError, match="truncated"):
        check_candidate_depth(
            "vector",
            "q01",
            candidate_count=10,
            unique_doc_count=1,
            ks=(1, 3),
            candidate_cap=10,
            corpus_chunk_count=17,
            corpus_doc_count=4,
        )


def test_rerank_window_is_treated_as_a_method_definition() -> None:
    """The reviewed top-10 rerank window legitimately bounds what it can surface."""
    check_candidate_depth(
        "hybrid+rules",
        "q01",
        candidate_count=10,
        unique_doc_count=1,
        ks=(1, 3),
        candidate_cap=10,
        corpus_chunk_count=17,
        corpus_doc_count=4,
        cap_is_method_definition=True,
    )


def test_cutoff_larger_than_corpus_only_needs_corpus_documents() -> None:
    check_candidate_depth(
        "bm25",
        "q01",
        candidate_count=10,
        unique_doc_count=4,
        ks=(1, 99),
        candidate_cap=10,
        corpus_chunk_count=17,
        corpus_doc_count=4,
    )


# ------------------------------------------------- bundled fixed query set


def test_bundled_query_set_has_exactly_24_rows(queries_path) -> None:
    queries = load_queries(queries_path)
    assert EXPECTED_QUERY_COUNT == 24
    assert len(queries) == EXPECTED_QUERY_COUNT
    assert [q.query_id for q in queries] == [f"q{i:02d}" for i in range(1, 25)]


def test_bundled_query_ids_are_unique(queries_path) -> None:
    ids = [q.query_id for q in load_queries(queries_path)]
    assert len(set(ids)) == len(ids)


def test_bundled_gold_labels_match_the_reviewed_set(queries_path) -> None:
    queries = load_queries(queries_path)
    expected = {
        **{f"q{i:02d}": "openwrt_ubus_guide.md" for i in range(1, 7)},
        **{f"q{i:02d}": "openwrt_firewall_setup.md" for i in range(7, 13)},
        **{f"q{i:02d}": "esxi_storage_management.md" for i in range(13, 19)},
        **{f"q{i:02d}": "docker_homelab_services.md" for i in range(19, 25)},
    }
    assert {q.query_id: q.gold_doc_ids[0] for q in queries} == expected
    assert all(len(q.gold_doc_ids) == 1 for q in queries)


def test_bundled_gold_labels_exist_in_the_week9_corpus(queries_path, retriever) -> None:
    validate_gold_doc_ids(load_queries(queries_path), retriever.document_ids)


def test_bundled_query_set_contains_chinese_queries(queries_path) -> None:
    """The set must exercise the mixed-language tokenizer, not only English."""
    queries = load_queries(queries_path)
    assert any(any("一" <= ch <= "鿿" for ch in q.query) for q in queries)
    assert any(q.query.isascii() for q in queries)


def test_bundled_query_set_hash_is_stable(queries_path) -> None:
    assert file_sha256(queries_path) == file_sha256(queries_path)
    assert len(file_sha256(queries_path)) == 64
