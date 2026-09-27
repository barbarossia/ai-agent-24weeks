"""Tokenizer contract tests for ``week10-mixed-cjk-v1``.

These assert exact token output, not just containment, because the tokenizer
version is part of the reproducibility contract of the whole lab.
"""

from __future__ import annotations

from production_rag_lab.lexical import (
    TOKENIZER_VERSION,
    index_text,
    normalize_text,
    tokenize,
    unique_tokens,
)

from conftest import make_chunk


def test_tokenizer_version_is_pinned() -> None:
    assert TOKENIZER_VERSION == "week10-mixed-cjk-v1"


def test_mixed_cjk_and_latin_example_from_the_runbook() -> None:
    # The approved runbook's worked example, as an exact ordered token list.
    assert tokenize("VMFS 数据存储") == [
        "vmfs",
        "数",
        "据",
        "存",
        "储",
        "数据",
        "据存",
        "存储",
    ]


def test_cjk_run_emits_unigrams_then_bigrams() -> None:
    assert tokenize("数据") == ["数", "据", "数据"]


def test_bigrams_never_cross_a_punctuation_boundary() -> None:
    # "据存" would be a bigram if the two runs were merged; punctuation must break it.
    assert tokenize("数据，存储") == ["数", "据", "数据", "存", "储", "存储"]
    assert "据存" not in tokenize("数据，存储")


def test_bigrams_never_cross_a_latin_boundary() -> None:
    tokens = tokenize("端口8080转发")
    assert tokens == ["端", "口", "端口", "8080", "转", "发", "转发"]


def test_latin_case_is_normalized_deterministically() -> None:
    assert tokenize("OpenWrt DNAT") == tokenize("openwrt dnat") == ["openwrt", "dnat"]


def test_technical_identifiers_survive_intact() -> None:
    tokens = tokenize("/ubus system.board esxcli pg_isready 192.168.1.50 -32002")
    for identifier in ("/ubus", "system.board", "esxcli", "pg_isready", "192.168.1.50", "-32002"):
        assert identifier in tokens


def test_hyphenated_identifier_keeps_compound_and_adds_components() -> None:
    # Fixed before any gold label was scored; see the tokenizer contract docstring.
    assert tokenize("ubus-over-HTTP") == [
        "ubus-over-http",
        "ubus",
        "over",
        "http",
    ]


def test_leading_hyphen_identifier_also_yields_numeric_component() -> None:
    assert tokenize("-32002") == ["-32002", "32002"]


def test_punctuation_only_and_empty_text_yield_no_tokens() -> None:
    for text in ("", "   ", "...", "-> / ---", "，。！", "\n\t"):
        assert tokenize(text) == []


def test_cjk_punctuation_is_ignored() -> None:
    assert tokenize("端口，转发。") == ["端", "口", "端口", "转", "发", "转发"]


def test_tokenization_is_deterministic() -> None:
    text = "OpenWrt 端口转发 DNAT vmfs 存储 esxcli"
    assert tokenize(text) == tokenize(text)


def test_unique_tokens_is_sorted_and_deduplicated() -> None:
    assert unique_tokens("beta alpha beta") == ["alpha", "beta"]
    # Repeating a query term must not change the distinct term set.
    assert unique_tokens("alpha alpha") == unique_tokens("alpha") == ["alpha"]


def test_normalize_text_lowercases_and_collapses_whitespace() -> None:
    assert normalize_text("  OpenWrt   DNAT\n  Rule  ") == "openwrt dnat rule"
    assert normalize_text("") == ""


def test_index_text_joins_title_heading_content_without_boosts() -> None:
    chunk = make_chunk("d.md#chunk_000", "d.md", "body text", title="Title", heading="H")
    assert index_text(chunk) == "Title\nH\nbody text"


def test_index_text_skips_empty_parts() -> None:
    chunk = make_chunk("d.md#chunk_000", "d.md", "body text")
    assert index_text(chunk) == "body text"
