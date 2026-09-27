"""CLI smoke tests: every sub-command, error paths, and UTF-8 output.

Each test invokes the real entrypoint in-process and asserts on exit codes and
output, so argument parsing, printing, and error handling are all covered without
a subprocess.
"""

from __future__ import annotations

import json

import pytest

from production_rag_lab.cli import main
from production_rag_lab.evaluation import load_queries

QUERY_TEXT = "OpenWrt 端口转发 DNAT"


@pytest.fixture()
def tiny_corpus(tmp_path):
    (tmp_path / "sample_doc.md").write_text(
        "# Sample\n\nAlpha and beta content about 端口转发.\n\n"
        "## Second\n\nGamma delta epsilon.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def tiny_queries(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text(
        json.dumps(
            {
                "query_id": "q01",
                "query": "端口转发 alpha",
                "gold_doc_ids": ["sample_doc.md"],
                "notes": "cli test",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------- help


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "production-rag-lab" in capsys.readouterr().out


def test_no_command_prints_help_and_exits_nonzero(capsys) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_unknown_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["nosuchcommand"])
    assert excinfo.value.code != 0


# ------------------------------------------------------------------- explain


def test_explain_prints_the_engineering_guide(capsys) -> None:
    assert main(["explain"]) == 0
    out = capsys.readouterr().out
    for topic in ("BM25", "SEMANTIC", "HYBRID", "RERANKING", "QUERY REWRITE", "CONTEXT COMPRESSION"):
        assert topic in out
    assert "c = 60" in out
    # The mock embedder caveat must be stated wherever the dense baseline appears.
    assert "learned semantic model" in out


# --------------------------------------------------------------------- demo


def test_demo_runs_offline(tiny_corpus, capsys) -> None:
    assert main(["demo", "--data-dir", str(tiny_corpus)]) == 0
    out = capsys.readouterr().out
    assert "[VECTOR]" in out
    assert "[BM25]" in out
    assert "[HYBRID]" in out
    assert "[HYBRID+RULES]" in out
    assert "MockEmbeddingProvider" in out


def test_demo_accepts_a_custom_query(tiny_corpus, capsys) -> None:
    assert main(["demo", "--data-dir", str(tiny_corpus), "--query", "alpha"]) == 0
    assert "alpha" in capsys.readouterr().out


# ------------------------------------------------------------------- search


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_search_supports_every_method(tiny_corpus, capsys, method: str) -> None:
    assert main(["search", QUERY_TEXT, "--data-dir", str(tiny_corpus), "--method", method]) == 0
    out = capsys.readouterr().out
    assert f"Search ({method})" in out
    assert "sample_doc.md#chunk_" in out


def test_search_explain_prints_score_details(tiny_corpus, capsys) -> None:
    assert main(["search", QUERY_TEXT, "--data-dir", str(tiny_corpus), "--explain"]) == 0
    out = capsys.readouterr().out
    assert "rrf" in out or "bm25 terms" in out


def test_search_rerank_is_labelled_separately(tiny_corpus, capsys) -> None:
    assert (
        main(
            [
                "search",
                QUERY_TEXT,
                "--data-dir",
                str(tiny_corpus),
                "--rerank",
                "rules",
                "--explain",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Search (hybrid+rules)" in out
    assert "exact_phrase=" in out


# ---------------------------- regression: rerank/method mismatch (H004/H007)
#
# `--method vector|bm25 --rerank rules` used to return the hybrid RRF candidates
# while reporting the requested method. These tests pin both halves of the fix:
# the combination is rejected, and no misleading JSON payload is emitted.


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_cli_rejects_rules_rerank_on_single_retriever_methods(tiny_corpus, capsys, method) -> None:
    exit_code = main(
        [
            "search",
            QUERY_TEXT,
            "--data-dir",
            str(tiny_corpus),
            "--method",
            method,
            "--rerank",
            "rules",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == "", "no successful result may be printed"
    assert "Error" in captured.err
    assert "hybrid" in captured.err
    assert method in captured.err


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_cli_rejected_combination_emits_no_json(tiny_corpus, capsys, method) -> None:
    """The critical auditability property: no misleading JSON on stdout."""
    exit_code = main(
        [
            "search",
            QUERY_TEXT,
            "--data-dir",
            str(tiny_corpus),
            "--method",
            method,
            "--rerank",
            "rules",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)
    # The error must not even leak a method claim into stdout.
    assert f'"{method}"' not in captured.out


def test_cli_hybrid_plus_rules_json_declares_its_hybrid_base(tiny_corpus, capsys) -> None:
    assert (
        main(
            [
                "search",
                QUERY_TEXT,
                "--data-dir",
                str(tiny_corpus),
                "--method",
                "hybrid",
                "--rerank",
                "rules",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "hybrid"
    assert payload["rerank"] == "rules"
    assert payload["mode"] == "hybrid+rules"
    assert payload["results"]
    for result in payload["results"]:
        assert result["score_kind"] == "rules_rerank"
        assert result["explanation"]["base_method"] == "hybrid"
        assert result["explanation"]["mode"] == "hybrid+rules"
        assert result["explanation"]["rerank"] == "rules"


def test_cli_json_mode_without_rerank_is_plain_method(tiny_corpus, capsys) -> None:
    for method in ("vector", "bm25", "hybrid"):
        assert main(["search", QUERY_TEXT, "--data-dir", str(tiny_corpus), "--method", method, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["method"] == method
        assert payload["rerank"] is None
        assert payload["mode"] == method
        for result in payload["results"]:
            assert "base_method" not in result["explanation"]


def test_cli_default_method_is_hybrid_so_bare_rerank_is_valid(tiny_corpus, capsys) -> None:
    """`--rerank rules` without `--method` is valid because the default is hybrid."""
    assert main(["search", QUERY_TEXT, "--data-dir", str(tiny_corpus), "--rerank", "rules", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "hybrid"
    assert payload["mode"] == "hybrid+rules"


def test_cli_rerank_help_states_the_hybrid_only_constraint(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["search", "--help"])
    # argparse wraps help text to the terminal width, so compare on normalized text.
    out = " ".join(capsys.readouterr().out.split())
    assert "--method hybrid" in out
    assert "hybrid top-10" in out
    assert "undefined for a single retriever ranking" in out


def test_demo_and_eval_still_accept_their_own_rerank_usage(tiny_corpus, tiny_queries, capsys) -> None:
    """The fix must not disturb the internal hybrid+rules paths of demo/eval."""
    assert main(["demo", "--data-dir", str(tiny_corpus)]) == 0
    assert "[HYBRID+RULES]" in capsys.readouterr().out
    assert (
        main(
            [
                "eval",
                "--data-dir",
                str(tiny_corpus),
                "--queries",
                str(tiny_queries),
                "--expect-queries",
                "1",
            ]
        )
        == 0
    )
    assert "hybrid+rules" in capsys.readouterr().out


def test_search_json_output_is_parseable(tiny_corpus, capsys) -> None:
    assert main(["search", "alpha", "--data-dir", str(tiny_corpus), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "hybrid"
    assert payload["results"]
    assert payload["results"][0]["chunk_id"].startswith("sample_doc.md#chunk_")


def test_search_top_k_limits_results(tiny_corpus, capsys) -> None:
    assert main(["search", "alpha", "--data-dir", str(tiny_corpus), "--top-k", "1"]) == 0
    assert "1 result(s)" in capsys.readouterr().out


def test_search_with_no_results_reports_none(tmp_path, capsys) -> None:
    """BM25 returns nothing when no query term matches; the dense baseline always ranks."""
    (tmp_path / "empty_doc.md").write_text("# T\n\n---\n", encoding="utf-8")
    assert main(["search", "zzzznotfound", "--data-dir", str(tmp_path), "--method", "bm25"]) == 0
    assert "(no results)" in capsys.readouterr().out


def test_unknown_method_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["search", "alpha", "--method", "telepathy"])
    assert excinfo.value.code != 0


def test_unknown_rerank_mode_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["search", "alpha", "--rerank", "neural"])
    assert excinfo.value.code != 0


def test_missing_data_dir_exits_nonzero(tmp_path, capsys) -> None:
    assert main(["search", "alpha", "--data-dir", str(tmp_path / "nope")]) == 1
    assert "Error" in capsys.readouterr().err


# --------------------------------------------------------------------- eval


def test_eval_runs_on_the_bundled_query_set(capsys) -> None:
    assert main(["eval", "--k", "1,3"]) == 0
    out = capsys.readouterr().out
    assert "Macro document-level Hit@k" in out
    assert "Query count" in out and "24" in out
    assert "Query set sha256" in out
    for method in ("vector", "bm25", "hybrid", "hybrid+rules"):
        assert method in out
    assert "k counts unique retrieved DOCUMENTS, never chunks" in out


def test_eval_reports_the_documented_configuration(capsys) -> None:
    assert main(["eval"]) == 0
    out = capsys.readouterr().out
    assert "week10-mixed-cjk-v1" in out
    assert "1.5 / 0.75" in out
    assert "RRF c" in out and "60" in out
    assert "MockEmbeddingProvider" in out


def test_eval_accepts_custom_cutoffs(capsys) -> None:
    assert main(["eval", "--k", "1,2,3,4"]) == 0
    out = capsys.readouterr().out
    assert "Hit@1" in out and "Hit@2" in out and "Hit@4" in out


def test_eval_method_subset_is_accepted(capsys) -> None:
    assert main(["eval", "--methods", "bm25,hybrid"]) == 0
    out = capsys.readouterr().out
    assert "bm25" in out and "hybrid" in out
    assert "hybrid+rules" not in out.split("Notes")[0].split("Retrieved")[0]


def test_eval_json_output_is_parseable(capsys) -> None:
    assert main(["eval", "--json", "--methods", "hybrid"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["query_count"] == 24
    assert payload["config"]["rrf_c"] == 60
    assert payload["config"]["bm25_k1"] == 1.5
    assert payload["config"]["bm25_b"] == 0.75
    assert payload["metric"].startswith("document-level")
    assert len(payload["query_set"]["queries"]) == 24
    assert len(payload["report"]["methods"]) == 1
    assert len(payload["report"]["methods"][0]["per_query"]) == 24


def test_eval_is_byte_identical_across_runs(capsys) -> None:
    assert main(["eval", "--json", "--methods", "bm25"]) == 0
    first = capsys.readouterr().out
    assert main(["eval", "--json", "--methods", "bm25"]) == 0
    second = capsys.readouterr().out
    assert first == second


def test_eval_on_a_tiny_custom_setup(tiny_corpus, tiny_queries, capsys) -> None:
    assert (
        main(
            [
                "eval",
                "--data-dir",
                str(tiny_corpus),
                "--queries",
                str(tiny_queries),
                "--expect-queries",
                "1",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Query count" in out
    assert "1" in out


def test_eval_rejects_a_missing_query_file(tiny_corpus, tmp_path, capsys) -> None:
    assert (
        main(
            [
                "eval",
                "--data-dir",
                str(tiny_corpus),
                "--queries",
                str(tmp_path / "nope.jsonl"),
            ]
        )
        == 1
    )
    assert "Error" in capsys.readouterr().err


def test_eval_rejects_an_empty_query_file(tiny_corpus, tmp_path, capsys) -> None:
    bad = tmp_path / "empty.jsonl"
    bad.write_text("\n", encoding="utf-8")
    assert main(["eval", "--data-dir", str(tiny_corpus), "--queries", str(bad)]) == 1
    assert "Error" in capsys.readouterr().err


def test_eval_rejects_unknown_gold_document_ids(tiny_corpus, tmp_path, capsys) -> None:
    bad = tmp_path / "bad_gold.jsonl"
    bad.write_text(
        json.dumps(
            {"query_id": "q01", "query": "alpha", "gold_doc_ids": ["not_in_corpus.md"]}
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["eval", "--data-dir", str(tiny_corpus), "--queries", str(bad)]) == 1
    assert "Unknown gold document ID" in capsys.readouterr().err


def test_eval_rejects_a_wrong_query_count(tiny_corpus, tiny_queries, capsys) -> None:
    assert (
        main(
            [
                "eval",
                "--data-dir",
                str(tiny_corpus),
                "--queries",
                str(tiny_queries),
                "--expect-queries",
                "24",
            ]
        )
        == 1
    )
    assert "Expected 24 queries" in capsys.readouterr().err


def test_eval_rejects_non_positive_cutoffs(capsys) -> None:
    assert main(["eval", "--k", "0"]) == 1
    assert "positive" in capsys.readouterr().err


def test_eval_rejects_malformed_cutoffs(capsys) -> None:
    assert main(["eval", "--k", "one"]) == 1
    assert "invalid cutoff" in capsys.readouterr().err


def test_eval_rejects_unknown_methods(capsys) -> None:
    assert main(["eval", "--methods", "bm25,telepathy"]) == 1
    assert "unknown method" in capsys.readouterr().err


# ------------------------------------------------------------------- unicode


def test_chinese_output_is_preserved(capsys) -> None:
    """The mixed-language query set must round-trip through the JSON report."""
    assert main(["eval", "--json", "--methods", "bm25"]) == 0
    payload = json.loads(capsys.readouterr().out)
    queries = payload["query_set"]["queries"]
    by_id = {entry["query_id"]: entry["query"] for entry in queries}
    # q13 is a mixed Chinese/English query from the reviewed fixed set.
    assert by_id["q13"] == "VMFS datastore 和 NFS datastore 的存储来源有什么区别？"
    assert any("一" <= ch <= "鿿" for entry in queries for ch in entry["query"])
    assert all(entry["gold_doc_ids"] for entry in queries)


def test_chinese_queries_are_accepted(tiny_corpus, capsys) -> None:
    assert main(["search", "端口转发", "--data-dir", str(tiny_corpus), "--explain"]) == 0
    assert "端口" in capsys.readouterr().out


def test_bundled_query_file_is_untouched_by_eval(queries_path, capsys) -> None:
    before = queries_path.read_bytes()
    assert main(["eval"]) == 0
    capsys.readouterr()
    assert queries_path.read_bytes() == before
    assert len(load_queries(queries_path)) == 24
