"""Command Line Interface for the Week 10 Production RAG Lab.

Sub-commands
------------
``demo``     end-to-end walkthrough of all three methods on one query
``search``   run one retrieval with optional ``--explain``
``eval``     macro **document-level** Hit@k over the fixed 24-row query set
``explain``  printed engineering guide (BM25, hybrid fusion, reranking, and the
             two note-level topics: query rewrite and context compression)

Runtime is fully offline: no network access, no API key, no hosted model, no
database. All output is deterministic and contains no timings, so repeated runs are
byte-identical.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - platform dependent
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - platform dependent
        pass

from production_rag_lab.evaluation import (
    DEFAULT_KS,
    EvalDataError,
    check_candidate_depth,
    evaluate,
    file_sha256,
    load_queries,
    validate_gold_doc_ids,
)
from production_rag_lab.lexical import DEFAULT_B, DEFAULT_K1, TOKENIZER_VERSION
from production_rag_lab.paths import get_default_queries_path
from production_rag_lab.rerank import DEFAULT_RERANK_CANDIDATES, rule_rerank
from production_rag_lab.retrieval import (
    DEFAULT_TOP_K,
    EMBEDDING_DIMENSION,
    METHODS,
    RERANK_MODES,
    ProductionRagRetriever,
    reported_mode,
    validate_rerank_combination,
)

PROG = "production-rag-lab"
#: Method label used for the separately reported deterministic rerank variant.
RERANKED_METHOD_LABEL = reported_mode("hybrid", "rules")
#: Order in which methods are evaluated and printed.
METHOD_ORDER: tuple[str, ...] = (*METHODS, RERANKED_METHOD_LABEL)

_SEPARATOR = "=" * 78
_RULE = "-" * 78


# --------------------------------------------------------------------- helpers


def _parse_ks(raw: str) -> tuple[int, ...]:
    """Parse a ``--k`` value such as ``1,3`` into sorted unique positive cutoffs."""
    cutoffs: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"invalid cutoff {part!r} in --k {raw!r}") from exc
        if value <= 0:
            raise ValueError(f"cutoffs must be positive, got {value}")
        cutoffs.append(value)
    if not cutoffs:
        raise ValueError("--k requires at least one positive cutoff, e.g. --k 1,3")
    return tuple(sorted(set(cutoffs)))


def _parse_methods(raw: str) -> tuple[str, ...]:
    """Parse ``--methods`` preserving the canonical reporting order."""
    requested = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in requested if name not in METHOD_ORDER]
    if unknown:
        raise ValueError(
            f"unknown method(s): {', '.join(unknown)}; expected any of "
            f"{', '.join(METHOD_ORDER)}"
        )
    if not requested:
        raise ValueError("--methods requires at least one method name")
    return tuple(name for name in METHOD_ORDER if name in set(requested))


def _build_retriever(data_dir: str | None) -> ProductionRagRetriever:
    return ProductionRagRetriever(Path(data_dir) if data_dir else None)


def _retrieval_options(retriever: ProductionRagRetriever) -> list[tuple[str, str]]:
    """Return the deterministic configuration block shared by every command."""
    return [
        ("Corpus directory", str(retriever.data_dir.resolve())),
        ("Documents", str(retriever.doc_count)),
        ("Chunks", str(retriever.chunk_count)),
        ("Tokenizer", TOKENIZER_VERSION),
        ("BM25 k1 / b", f"{DEFAULT_K1} / {DEFAULT_B}"),
        ("RRF c", str(retriever.rrf_c)),
        (
            "Vector provider",
            f"{retriever.vector_provider} (offline hash projection, dim={EMBEDDING_DIMENSION})",
        ),
        ("Candidate depth per retriever", str(retriever.candidate_depth)),
        ("Rerank candidate limit", str(DEFAULT_RERANK_CANDIDATES)),
    ]


def _print_options(options: list[tuple[str, str]]) -> None:
    width = max(len(label) for label, _ in options)
    for label, value in options:
        print(f"  {label.ljust(width)} : {value}")


def _print_header(title: str) -> None:
    print(_SEPARATOR)
    print(f" {title}")
    print(_SEPARATOR)
    print()


def _format_explanation(result) -> str:
    """Render a result's explanation payload as compact readable text."""
    lines: list[str] = []
    for key in sorted(result.explanation):
        value = result.explanation[key]
        if key == "fused":
            ranks = value["ranks"]
            contributions = value["contributions"]
            rendered = ", ".join(
                f"{name}=rank {ranks[name]}/+{contributions[name]:.6f}"
                for name in sorted(ranks)
            )
            lines.append(f"      rrf       : {rendered}")
        elif key == "features":
            lines.append(
                "      rerank    : exact_phrase="
                f"{value['exact_phrase_match']}, distinct_query_tokens="
                f"{value['matched_token_count']}, rrf_score={value['rrf_score']:.6f}"
            )
            if value["matched_tokens"]:
                lines.append(
                    "      tokens    : " + ", ".join(value["matched_tokens"][:12])
                )
        elif key == "matched_terms":
            lines.append(
                "      bm25 terms: " + (", ".join(value) if value else "(none)")
            )
        else:
            lines.append(f"      {key.ljust(10)}: {value}")
    return "\n".join(lines)


def _print_results(query: str, results: list, *, explain: bool) -> None:
    print(f'Query: "{query}"')
    if not results:
        print("  (no results)")
        print()
        return
    print(f"  {len(results)} result(s), best first:")
    for result in results:
        print(
            f"  #{result.rank} [{result.score_kind}={result.score:.6f}] "
            f"{result.chunk_id}"
        )
        print(f"      document : {result.doc_id}")
        print(f"      heading  : {result.heading}")
        print(f"      source   : {result.source_file} (category={result.category})")
        print(f"      snippet  : {result.snippet}")
        if explain:
            print(_format_explanation(result))
    print()


# ---------------------------------------------------------------------- commands


def run_search(args: argparse.Namespace) -> int:
    # Validate the (method, rerank) combination *before* doing any work, so an
    # unsupported combination can never reach a successful-looking JSON payload.
    validate_rerank_combination(args.method, args.rerank)
    retriever = _build_retriever(args.data_dir)
    results = retriever.search(
        args.query, method=args.method, top_k=args.top_k, rerank=args.rerank
    )
    mode = reported_mode(args.method, args.rerank)
    if args.json:
        print(
            json.dumps(
                {
                    "query": args.query,
                    # Unambiguous provenance: the retrieval method, the rerank mode
                    # applied to it, and the combined label. `mode` never hides the
                    # base method it was derived from.
                    "method": args.method,
                    "rerank": args.rerank,
                    "mode": mode,
                    "top_k": args.top_k,
                    "results": [result.as_dict() for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _print_header(f"Week 10 — Production RAG Lab · Search ({mode})")
    _print_options(_retrieval_options(retriever))
    print()
    _print_results(args.query, results, explain=args.explain)
    return 0


def run_demo(args: argparse.Namespace) -> int:
    retriever = _build_retriever(args.data_dir)
    _print_header("Week 10 — Production RAG Lab · End-to-End Demo")
    _print_options(_retrieval_options(retriever))
    print("  All methods below see the identical corpus, chunks, and query.")
    print()

    query = args.query
    print(_RULE)
    print(f'Query: "{query}"')
    print(_RULE)
    print()

    for method in METHODS:
        results = retriever.search(query, method=method, top_k=args.top_k)
        print(f"[{method.upper()}]")
        _print_results(query, results, explain=False)

    reranked = retriever.search(query, method="hybrid", top_k=args.top_k, rerank="rules")
    print(f"[{RERANKED_METHOD_LABEL.upper()}] (reported separately from base hybrid)")
    _print_results(query, reranked, explain=False)

    print("=" * 78)
    print(" Interpretation")
    print("=" * 78)
    print("  * The dense baseline uses Week 9's deterministic MockEmbeddingProvider,")
    print("    which is an offline hash projection, not a learned semantic model.")
    print("  * BM25 scores and cosine similarities are never added together; hybrid")
    print("    fuses ranks with RRF, so their score scales stay incomparable-safe.")
    print("  * Reranking is a bounded deterministic rule demonstration, not a neural")
    print("    cross-encoder, and no quality threshold is claimed.")
    print("  * Run `production-rag-lab eval` for document-level Hit@k on the fixed")
    print("    24-row gold-labeled query set.")
    print()
    return 0


def run_eval(args: argparse.Namespace) -> int:
    ks = _parse_ks(args.k)
    methods = _parse_methods(args.methods)
    retriever = _build_retriever(args.data_dir)
    queries = load_queries(args.queries)
    validate_gold_doc_ids(queries, retriever.document_ids)
    if len(queries) != args.expect_queries:
        raise EvalDataError(
            f"Expected {args.expect_queries} queries in {args.queries}, found {len(queries)}"
        )

    rankings: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for method in methods:
        base_method = "hybrid" if method == RERANKED_METHOD_LABEL else method
        rerank = "rules" if method == RERANKED_METHOD_LABEL else None
        per_query: dict[str, list[tuple[str, str]]] = {}
        for query in queries:
            if rerank == "rules":
                candidate_cap = DEFAULT_RERANK_CANDIDATES
                fused = retriever.fuse(query.query)[:candidate_cap]
                ranked = [
                    (item.chunk_id, item.doc_id)
                    for item in _rerank_order(retriever, query.query, fused)
                ]
            else:
                candidate_cap = retriever.candidate_depth
                ranked = retriever.ranking(query.query, base_method)
            documents = _unique_docs(ranked)
            check_candidate_depth(
                method,
                query.query_id,
                candidate_count=len(ranked),
                unique_doc_count=len(documents),
                ks=ks,
                candidate_cap=candidate_cap,
                corpus_chunk_count=retriever.chunk_count,
                corpus_doc_count=retriever.doc_count,
                cap_is_method_definition=(rerank == "rules"),
            )
            per_query[query.query_id] = ranked
        rankings[method] = per_query

    report = evaluate(queries, rankings, ks)

    if args.json:
        print(
            json.dumps(
                {
                    "corpus": {
                        "data_dir": str(retriever.data_dir.resolve()),
                        "documents": retriever.doc_count,
                        "chunks": retriever.chunk_count,
                    },
                    "query_set": {
                        "path": str(Path(args.queries).resolve()),
                        "sha256": file_sha256(args.queries),
                        "count": len(queries),
                        "queries": [
                            {
                                "query_id": query.query_id,
                                "query": query.query,
                                "gold_doc_ids": list(query.gold_doc_ids),
                            }
                            for query in queries
                        ],
                    },
                    "config": {
                        "tokenizer": TOKENIZER_VERSION,
                        "bm25_k1": DEFAULT_K1,
                        "bm25_b": DEFAULT_B,
                        "rrf_c": retriever.rrf_c,
                        "candidate_depth": retriever.candidate_depth,
                        "rerank_candidates": DEFAULT_RERANK_CANDIDATES,
                        "vector_provider": retriever.vector_provider,
                    },
                    "metric": "document-level Hit@k over unique retrieved documents",
                    "report": report.as_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    options = [
        *[
            option
            for option in _retrieval_options(retriever)
            if option[0] not in {"Rerank candidate limit"}
        ],
        ("Query set", str(Path(args.queries).resolve())),
        ("Query count", str(len(queries))),
        ("Query set sha256", file_sha256(args.queries)),
        (
            "Metric",
            "document-level Hit@k; chunks ranked, collapsed to unique doc IDs, "
            "k counts unique docs",
        ),
        ("Cutoffs k", ", ".join(str(k) for k in ks)),
    ]

    _print_header("Week 10 — Production RAG Lab · Retrieval Evaluation")
    _print_options(options)
    print()

    print(_RULE)
    print(" Macro document-level Hit@k  (macro average of binary per-query hits)")
    print(_RULE)
    header = "  " + "method".ljust(16) + "".join(f"Hit@{k}".rjust(10) for k in ks)
    print(header)
    for method_report in report.methods:
        cells = "".join(
            f"{method_report.macro_hit_at_k[k]:.4f}".rjust(10) for k in ks
        )
        print("  " + method_report.method.ljust(16) + cells)
    print()

    print(_RULE)
    print(" Per-query binary hits as hit@k pairs, one column per method")
    print(_RULE)
    cell_width = max(
        len(f"{method_report.method}@{k}")
        for method_report in report.methods
        for k in ks
    ) + 2
    print("  " + "query".ljust(8) + "".join(m.method.ljust(cell_width) for m in report.methods))
    for index in range(report.query_count):
        row = "  " + f"q{index + 1:02d}".ljust(8)
        for method_report in report.methods:
            outcome = method_report.per_query[index]
            cell = "/".join("1" if outcome.hit_at_k[k] else "0" for k in ks)
            row += cell.ljust(cell_width)
        print(row)
    print()

    print(_RULE)
    print(" Retrieved unique documents per query (first-occurrence order)")
    print(_RULE)
    for index, query in enumerate(queries):
        print(f"  {query.query_id}  gold={','.join(query.gold_doc_ids)}")
        for method_report in report.methods:
            outcome = method_report.per_query[index]
            documents = ", ".join(outcome.retrieved_doc_ids) or "(none)"
            print(f"      {method_report.method.ljust(16)}: {documents}")
    print()

    print(_RULE)
    print(" Notes")
    print(_RULE)
    print("  * k counts unique retrieved DOCUMENTS, never chunks.")
    print("  * A query with no results is a miss; the list is never padded.")
    print(f"  * This corpus has only {retriever.doc_count} documents, so Hit@3 can")
    print("    miss only when the gold document ranks 4th; Hit@1 is the informative")
    print("    column here. Add more documents before drawing conclusions.")
    print("  * 'hybrid+rules' reranks only the hybrid top-"
          f"{DEFAULT_RERANK_CANDIDATES} window, so it cannot surface a document")
    print("    that is absent from that window. It is reported separately on purpose:")
    print("    a bounded deterministic reranker is not guaranteed to improve results.")
    print("  * These numbers measure this four-document corpus with an offline mock")
    print("    embedder. They are not a production RAG benchmark and no quality")
    print("    threshold is asserted anywhere.")
    print()
    return 0


def _unique_docs(ranked: list[tuple[str, str]]) -> list[str]:
    documents: list[str] = []
    seen: set[str] = set()
    for _chunk_id, doc_id in ranked:
        if doc_id not in seen:
            seen.add(doc_id)
            documents.append(doc_id)
    return documents


def _rerank_order(retriever: ProductionRagRetriever, query: str, fused: list):
    """Apply the bounded deterministic reranker to a fused candidate set."""
    return rule_rerank(query, fused, retriever.chunks_by_id)


def run_explain(_args: argparse.Namespace) -> int:
    print(f"""
{_SEPARATOR}
 WEEK 10 — PRODUCTION RAG: RETRIEVAL QUALITY ENGINEERING
{_SEPARATOR}

1. BM25 (LEXICAL RETRIEVAL)
{_RULE}
   idf(t)   = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
   score(d) = SUM_t idf(t) * tf(t,d) * (k1 + 1)
                            / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

   * tf saturation: k1 controls how quickly repeated terms stop helping.
   * Length normalization: b controls how strongly long chunks are penalized.
   * k1 and b are explicit defaults (1.5 / 0.75 here) fixed BEFORE scoring, and are
     never tuned against the evaluation queries. Tuning belongs on a separate
     development set (Manning, Raghavan & Schuetze, IIR, "Okapi BM25").
   * BM25 has several legitimate IDF variants; the nonnegative smoothed form above
     is this lab's choice, not the only canonical formula.
   * Weakness: exact lexical overlap only. "Router", "gateway" and "R7800" share
     almost no tokens, so pure BM25 can miss paraphrases entirely.

2. SEMANTIC / DENSE RETRIEVAL
{_RULE}
   * Embeds text into a vector space and ranks by cosine similarity, so paraphrases
     with little vocabulary overlap can still score highly.
   * This lab reuses the Week 9 MockEmbeddingProvider: a DETERMINISTIC OFFLINE HASH
     PROJECTION. It is a teaching baseline for pipeline mechanics. It is NOT a
     learned semantic model and its scores say nothing about production embedding
     quality.
   * Weakness: dense scores are opaque, can drift with the model, and are hard to
     audit term by term.

3. HYBRID SEARCH VIA RRF
{_RULE}
   RRF(d) = SUM_r 1 / (c + rank_r(d))          c = 60

   * Never add raw BM25 and cosine scores: they are different scales, so a weighted
     sum would be arbitrary. RRF consumes RANKS only, so no calibration is needed.
   * Deterministic tie-breaks: score desc, best vector rank, best BM25 rank,
     chunk_id asc. Missing ranks contribute nothing.
   * Cormack, Clarke & Buettcher (SIGIR 2009) introduced RRF with c=60. Their
     results come from their own collections; nothing here promises a win here.

4. RERANKING
{_RULE}
   * Reranking reorders a small candidate set with a more expensive, more accurate
     scorer after cheap retrieval.
   * This lab's reranker is a bounded DETERMINISTIC RULE demonstration over the
     hybrid top-10: exact normalized query phrase, then count of distinct query
     tokens present, then the RRF score, then chunk_id. It is fully explainable
     and offline.
   * It is NOT a neural cross-encoder, and it makes no general quality claim.
   * Base hybrid and hybrid+rules are always reported separately so the effect of
     reranking stays isolated.

5. QUERY REWRITE (NOTE-LEVEL TOPIC, NOT IMPLEMENTED HERE)
{_RULE}
   * Rewrites a user query into a form the retriever handles better: synonym
     expansion, spelling normalization, decomposition of a multi-part question.
   * In production this usually needs an LLM, so it is out of scope for this
     offline lab. The deterministic lever available here is the tokenizer: the
     shared token contract plus hyphen-component expansion already reduces some
     vocabulary mismatch.

6. CONTEXT COMPRESSION (NOTE-LEVEL TOPIC, NOT IMPLEMENTED HERE)
{_RULE}
   * Reduces retrieved chunks to the smallest span that still answers the question,
     before paying for generation. Common techniques: sentence-level scoring,
     extractive summaries, or an LLM that rewrites chunks into tight context.
   * Not implemented here. This lab deliberately ends at retrieval and reranking:
     no LLM, no generation, no API key.

7. MEASURING INSTEAD OF GUESSING
{_RULE}
   * Methods are compared on ONE corpus, ONE chunk set, ONE query set.
   * The metric is DOCUMENT-LEVEL Hit@k: rank chunks, collapse to unique document
     IDs in first-hit order, count k over those documents, a query is a hit iff a
     gold document ID appears in the first k, macro-average over queries.
   * Chunk-level Hit@k is out of scope. No quality threshold is asserted and no
     claim is made that hybrid must win.
""")
    return 0


# ------------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Week 10 — Production RAG Lab: Vector Only vs BM25 vs Hybrid (RRF) "
            "retrieval with document-level Hit@k evaluation. Fully offline."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to run")

    def add_data_dir(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Corpus directory of *.md files (default: the read-only Week 9 corpus)",
        )

    demo_parser = subparsers.add_parser(
        "demo", help="Run the end-to-end comparison of all retrieval methods"
    )
    add_data_dir(demo_parser)
    demo_parser.add_argument(
        "--query",
        type=str,
        default="OpenWrt 端口转发 DNAT 配置",
        help="Query used for the walkthrough",
    )
    demo_parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K, help="Results per method"
    )
    demo_parser.set_defaults(handler=run_demo)

    explain_parser = subparsers.add_parser(
        "explain", help="Display the retrieval engineering guide"
    )
    explain_parser.set_defaults(handler=run_explain)

    search_parser = subparsers.add_parser("search", help="Execute one retrieval query")
    search_parser.add_argument("query", type=str, help="Search query string")
    search_parser.add_argument(
        "--method",
        type=str,
        default="hybrid",
        choices=list(METHODS),
        help="Retrieval method (default: hybrid)",
    )
    search_parser.add_argument(
        "--rerank",
        type=str,
        default=None,
        choices=list(RERANK_MODES),
        help=(
            "Optional deterministic rerank mode, reported as hybrid+rules. "
            "Only valid together with --method hybrid: rules reranking reorders "
            "the hybrid top-10 fused candidates, so it is undefined for a single "
            "retriever ranking."
        ),
    )
    search_parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K, help="Number of results"
    )
    search_parser.add_argument(
        "--explain", action="store_true", help="Print per-result score explanations"
    )
    search_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead"
    )
    add_data_dir(search_parser)
    search_parser.set_defaults(handler=run_search)

    eval_parser = subparsers.add_parser(
        "eval", help="Evaluate document-level Hit@k on the fixed query set"
    )
    add_data_dir(eval_parser)
    eval_parser.add_argument(
        "--queries",
        type=str,
        default=str(get_default_queries_path()),
        help="JSONL query set with gold document IDs",
    )
    eval_parser.add_argument(
        "--k",
        type=str,
        default=",".join(str(k) for k in DEFAULT_KS),
        help="Comma-separated cutoffs counting unique documents (default: 1,3)",
    )
    eval_parser.add_argument(
        "--methods",
        type=str,
        default=",".join(METHOD_ORDER),
        help=f"Comma-separated subset of: {','.join(METHOD_ORDER)}",
    )
    eval_parser.add_argument(
        "--expect-queries",
        type=int,
        default=24,
        help="Fail unless the query file holds exactly this many rows (default: 24)",
    )
    eval_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead"
    )
    eval_parser.set_defaults(handler=run_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args))
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"[!] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
