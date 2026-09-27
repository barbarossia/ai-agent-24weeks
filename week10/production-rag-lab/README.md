# Week 10 — Production RAG Lab

Runnable, fully **offline** comparison of three retrieval strategies over one shared
corpus, one shared chunk set, and one fixed gold-labeled query set:

| Method | What it is | Score kind |
|---|---|---|
| `vector` | Dense cosine retrieval over the Week 9 `MockEmbeddingProvider` | `cosine_similarity` |
| `bm25` | Bounded pure-Python Okapi BM25 with a mixed English/Chinese tokenizer | `bm25` |
| `hybrid` | Reciprocal Rank Fusion (`c = 60`) of the two rankings above | `rrf` |
| `hybrid+rules` | Optional bounded deterministic rule rerank of the hybrid top-10 | `rules_rerank` |

No network access, no API key, no hosted model, no database, no LLM. Runtime needs
Python 3.12 and `uv` only.

---

## 1. Install and run

```bash
cd week10/production-rag-lab

# 1. Create the environment and install (Week 9 is an editable local path dependency)
uv sync

# 2. Run the offline test suite
uv run pytest -v

# 3. End-to-end walkthrough of all methods on one query
uv run production-rag-lab demo

# 4. Single retrieval, any method
uv run production-rag-lab search "How do I inspect OpenWrt ubus interface status?" --method vector --top-k 3
uv run production-rag-lab search "OpenWrt 端口转发 DNAT" --method bm25 --top-k 3
uv run production-rag-lab search "OpenWrt 端口转发 DNAT" --method hybrid --top-k 3 --explain
uv run production-rag-lab search "OpenWrt 端口转发 DNAT" --method hybrid --rerank rules --top-k 3 --explain

# 5. Document-level Hit@k on the fixed 24-row query set
uv run production-rag-lab eval --k 1,3
uv run production-rag-lab eval --k 1,3 --json          # machine-readable

# 6. Printed engineering guide
uv run production-rag-lab explain
```

`python -m production_rag_lab <command>` works identically.

`uv sync` needs network access the first time to resolve/download `pydantic` and
`pytest`. **After that, every command above runs fully offline** — the lab itself
makes no network calls, reads no credentials, and touches no external service.

---

## 2. Reuse of Week 9

Week 9 is consumed as an **editable local path dependency**, never copied or
modified:

```toml
[project]
dependencies = ["vector-search-lab"]

[tool.uv.sources]
vector-search-lab = { path = "../../week9/vector-search-lab", editable = true }
```

The corpus is the read-only Week 9 corpus at `week9/vector-search-lab/data/`
(4 documents → 17 chunks), so `vector`, `bm25`, and `hybrid` provably rank the
**same chunk objects**. Only public Week 9 APIs are used (`Document`,
`MarkdownChunker`, `MockEmbeddingProvider`, `VectorSearchPipeline`,
`InMemoryVectorStore.get`); no Week 9 private attribute is touched and no Week 9
test is modified. A startup consistency check raises if the Week 10 chunk view and
the Week 9 vector index ever disagree.

Week 10's own data is just the query set: `data/eval_queries.jsonl`.

---

## 3. Tokenizer contract (`week10-mixed-cjk-v1`)

Text is lowercased, then scanned once left-to-right with a single alternation:

* ASCII runs `[a-z0-9_./-]+` are kept **whole**, so technical identifiers survive:
  `ubus-over-http`, `network.interface.dump`, `esxcli`, `pg_isready`,
  `192.168.1.50`, `-32002`.
* A compound ASCII token containing `-` additionally emits its non-empty
  components, so `ubus-over-http` also yields `ubus`, `over`, `http`. Dots,
  underscores, and slashes are **not** split: they are meaningful in this corpus.
* CJK ideograph runs (U+4E00–U+9FFF) emit every character in order, then every
  adjacent pair in order. Bigrams never cross punctuation or Latin text.
* Runs with no ASCII alphanumeric and no CJK character are dropped, so bullets,
  arrows, and ellipses never become tokens.

```text
"VMFS 数据存储"  ->  ['vmfs', '数', '据', '存', '储', '数据', '据存', '存储']
"ubus-over-HTTP" ->  ['ubus-over-http', 'ubus', 'over', 'http']
"... ->"          ->  []
```

**This is not Chinese word segmentation.** CJK character unigrams and bigrams are a
deliberately small, dependency-free baseline that lets a mixed corpus be matched
lexically. They create broad lexical overlap and are not claimed to be
linguistically correct. A dictionary segmenter such as `jieba` is a viable future
ablation behind an optional extra, using this same fixed query set — not part of
this lab.

---

## 4. BM25 contract

```text
idf(t)   = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(d) = Σ_t idf(t) * tf(t,d) * (k1 + 1)
                        / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
defaults: k1 = 1.5, b = 0.75
```

* `N` = indexed chunks (17), `df` = chunks containing the term, `tf` = token count,
  `|d|` and `avgdl` = token counts.
* **Fixed defaults.** `k1`/`b` were pinned before any gold label was scored and are
  never tuned against the evaluation queries. Parameter tuning belongs on a separate
  development set (Manning, Raghavan & Schütze, *Introduction to Information
  Retrieval*, "Okapi BM25").
* **One IDF variant.** BM25 has several legitimate IDF forms; the nonnegative
  smoothed form above is this lab's choice, not the only canonical formula.
* Each **distinct** query term is scored once; repeating a term does not
  multiply its weight. An empty/punctuation-only query returns no results.
* Single uniform indexed field: `title + heading + content`, no field boosts.
* Only chunks with `score > 0` are returned, so "no lexical match" is an honest
  empty result rather than a full corpus of zeros.
* Ordering: score descending, then `chunk_id` ascending. Term summation order and
  candidate iteration order are fixed, so scores are bit-reproducible.

---

## 5. Hybrid fusion (RRF, `c = 60`)

```text
RRF(d) = Σ_r 1 / (c + rank_r(d))        c = 60
```

A BM25 score and a cosine similarity are **incomparable scales**, so they are never
added or weighted together. RRF consumes only ranks, so no calibration is needed.
Deterministic ordering: score descending → best vector rank → best BM25 rank →
`chunk_id` ascending; a chunk missing from a ranking contributes nothing, and
duplicate `chunk_id`s inside one ranking collapse to their first occurrence.

`c = 60` follows Cormack, Clarke & Büttcher (SIGIR 2009). Their empirical results
come from their own test collections; nothing here claims RRF wins on this corpus.

---

## 6. Reranking (`hybrid+rules`)

A **bounded deterministic rule demonstration**, not a neural cross-encoder. It
reranks only the hybrid **top-10** candidates and returns a permutation of that set
— a larger input is a `ValueError`, and no candidate outside the input can appear.

Sort keys, in order:

1. exact match of the whitespace-normalized query as a substring of the chunk field;
2. count of **distinct** query tokens present in the chunk token set;
3. the incoming RRF score;
4. `chunk_id` ascending.

Base `hybrid` and `hybrid+rules` are **always reported separately**, so the effect of
reranking stays isolated. No quality claim is attached to it.

### Only valid with `--method hybrid`

Because it reorders the *fused* top-10, rules reranking is defined **only** for
`method="hybrid"`. Requesting it with `--method vector` or `--method bm25` is
rejected in both the public `ProductionRagRetriever.search()` API and the CLI:

```console
$ production-rag-lab search "OpenWrt 端口转发 DNAT" --method vector --rerank rules
[!] Error: rerank='rules' reranks the 'hybrid' top-10 candidates and is therefore
    only supported with method='hybrid'; got method='vector'. ...
$ echo $?
1
```

Rejecting it matters for auditability: accepting it would return the hybrid RRF
candidates while reporting the requested method, so the output would not be the
Vector Only or BM25 result it claimed to be. Structured output for the valid
combination is explicit about its base:

```jsonc
{
  "method": "hybrid",        // the retrieval method that ran
  "rerank": "rules",         // the rerank applied to it
  "mode": "hybrid+rules",    // combined label, never hides its base
  "results": [{ "score_kind": "rules_rerank",
                "explanation": { "mode": "hybrid+rules", "base_method": "hybrid", "rerank": "rules" } }]
}
```

`reported_mode()` and `validate_rerank_combination()` in `production_rag_lab.retrieval`
are the single source of truth for this rule, shared by the API and the CLI.

---

## 7. Evaluation: document-level Hit@k

Methods rank **chunks**. For each method and query:

1. walk the ranked chunks in order, keeping only the **first occurrence** of each
   `doc_id` (collapse to unique document IDs);
2. let `R_q(k)` be the first `k` unique document IDs — **`k` counts unique
   documents, never chunks**;
3. `hit_q@k = 1` iff `R_q(k) ∩ gold_doc_ids` is non-empty;
4. `macro Hit@k = (Σ_q hit_q@k) / Q`, every query weighted equally.

No results is a miss; the list is never padded. This is a binary "any gold document
retrieved" metric — **not** precision, and **chunk-level Hit@k is out of scope**.

Gold labels live in `data/eval_queries.jsonl` (24 rows, `q01`–`q24`, one reviewed
gold document each). They are validated against the corpus: an unknown gold document
ID is a hard error, never a silent remap, and the labels are never derived from or
adjusted because of system output.

```bash
uv run production-rag-lab eval --k 1,3
uv run production-rag-lab eval --k 1,2,3,4
uv run production-rag-lab eval --methods vector,bm25,hybrid
```

---

## 8. Measured results

Measured on **2026-09-27** with Python 3.12.13 / `uv 0.11.16`, corpus
`week9/vector-search-lab/data` (4 documents, 17 chunks), tokenizer
`week10-mixed-cjk-v1`, `k1=1.5`, `b=0.75`, `c=60`, candidate depth 20, rerank window
10, query set `data/eval_queries.jsonl`
(sha256 `b10fec276237b939c4c7371176db94dd52adcc9221c2a5a274e31440eda1e7f2`).

| method | Hit@1 | Hit@3 |
|---|---|---|
| `vector` | 0.7500 (18/24) | 1.0000 (24/24) |
| `bm25` | 1.0000 (24/24) | 1.0000 (24/24) |
| `hybrid` | 1.0000 (24/24) | 1.0000 (24/24) |
| `hybrid+rules` | 0.9583 (23/24) | 1.0000 (24/24) |

Reproduce with `uv run production-rag-lab eval --k 1,3`; the output contains no
timings and is byte-identical across runs. The per-query hit table and the
retrieved-document order for every query are printed by the same command.

### How to read these numbers honestly

* **They are not a benchmark.** Four hand-written documents and a mock embedder can
  only demonstrate retrieval mechanics.
* **Hit@3 is nearly uninformative here.** With only 4 documents, Hit@3 misses only
  when the gold document ranks 4th. Hit@1 is the informative column. A larger corpus
  is required before any comparison means much.
* **BM25 scoring 24/24 here does not mean lexical retrieval is "better".** The gold
  labels name the document that literally contains the queried identifiers, so exact
  lexical overlap is an unusually strong signal on this corpus. The `vector` misses
  (q12, q14, q16, q19) are all paraphrases with little shared vocabulary — exactly
  the weakness a real semantic model would be expected to cover and this mock cannot.
* **The rule reranker measurably did not help.** `hybrid+rules` loses q08 at Hit@1
  versus base `hybrid` (0.9583 vs 1.0000). The reranker was **not** modified in
  response; the design was fixed in advance and the observation is reported as
  measured. A bounded heuristic reranker is not guaranteed to improve ranking.
* **No threshold is asserted anywhere**, in code or docs, and no test asserts that
  hybrid wins.

---

## 9. Layout

```text
production-rag-lab/
├── .python-version              # 3.12
├── pyproject.toml               # editable local Week 9 dependency + pytest
├── uv.lock                      # local lockfile
├── data/eval_queries.jsonl      # fixed 24-row gold-labeled query set
├── src/production_rag_lab/
│   ├── __init__.py              # public API
│   ├── __main__.py              # python -m entrypoint
│   ├── cli.py                   # demo / search / eval / explain
│   ├── paths.py                 # default corpus + query locations
│   ├── lexical.py               # tokenizer, BM25 index, explanations
│   ├── fusion.py                # RRF (c=60) + deterministic ordering
│   ├── rerank.py                # bounded deterministic top-10 rerank
│   ├── retrieval.py             # corpus loader, vector adapter, orchestrator
│   └── evaluation.py            # JSONL validation, doc collapse, Hit@k
└── tests/                       # 210 offline tests
    ├── test_tokenizer.py
    ├── test_bm25.py
    ├── test_vector_adapter.py
    ├── test_fusion.py
    ├── test_rerank.py
    ├── test_evaluation.py
    ├── test_cli.py
    └── test_end_to_end.py
```

## 10. Test coverage

`uv run pytest -v` → **210 passed** (2026-09-27, fully offline).

| Area | File | What is pinned |
|---|---|---|
| Tokenizer | `test_tokenizer.py` | exact token output, CJK/Latin boundaries, identifier integrity, punctuation and empty handling, determinism |
| BM25 | `test_bm25.py` | hand-computed scores and IDF, agreement with an independent transcription of the formula, length normalization, `b=0`, term-once semantics, tie order, explanations summing to the score |
| Vector adapter | `test_vector_adapter.py` | Week 9 public-API reuse, offline provider, chunk/index consistency guard, deterministic ranking, empty query |
| RRF | `test_fusion.py` | `c=60`, hand-calculated contributions, 1-based ranks, missing lists contribute zero, duplicate collapse, tie-break order, `top_k` |
| Reranker | `test_rerank.py` | phrase → token count → RRF → `chunk_id` ordering, top-10 bound, output is a permutation of the input |
| Evaluation | `test_evaluation.py` | JSONL validation failures, gold IDs validated against the corpus, document collapse, `k` counts documents, macro averaging, candidate-depth guard, bundled set integrity |
| CLI | `test_cli.py` | every sub-command, exit codes, error paths, JSON output, UTF-8, byte-identical repeat runs, rules-rerank rejected for `vector`/`bm25` with no JSON emitted, valid `hybrid+rules` provenance |
| End to end | `test_end_to_end.py` | shared corpus/chunks, 24 queries evaluated, macro values consistent with per-query hits, hybrid ⊆ vector ∪ bm25, determinism, no timings, no threshold assertions, API-level rules-rerank rejection |

## 11. Limitations

* **Mock dense baseline.** `MockEmbeddingProvider` is a deterministic offline hash
  projection, useful for pipeline mechanics only. Its cosine scores say nothing
  about production embedding quality, and no production semantic model is used or
  permitted here.
* **Four documents, 17 chunks.** Every Hit@k number is narrow and instructional. Hit@3
  in particular cannot discriminate much on a 4-document corpus.
* **Single-document gold labels.** Relevance coverage is limited; there is no graded
  relevance and no multi-document gold case.
* **No Chinese word segmentation.** CJK unigram/bigram matching produces broad
  lexical overlap.
* **Week 9 `chunk_size`/`chunk_overlap` are targets, not hard bounds.** A long
  paragraph can exceed the target chunk size; no strict chunk-size bound is claimed.
* **No query rewrite, no context compression, no generation.** Both are note-level
  topics only; the lab deliberately ends at retrieval and reranking.
* **Labels must be re-reviewed if the corpus changes.** Validation fails loudly rather
  than remapping.
* **Not tuned.** `k1`, `b`, `c`, and the tokenizer were fixed before scoring and were
  never adjusted based on these results.

## 12. Sources

* Manning, Raghavan & Schütze, *Introduction to Information Retrieval*, "Okapi BM25: a
  non-binary model" — <https://nlp.stanford.edu/IR-book/html/htmledition/okapi-bm25-a-non-binary-model-1.html>
* Cormack, Clarke & Büttcher, "Reciprocal Rank Fusion outperforms Condorcet and
  individual Rank Learning Methods", SIGIR 2009 —
  <https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf>
* Python 3.12 `re` documentation (Unicode `str`; no Chinese word segmenter) —
  <https://docs.python.org/3.12/library/re.html>
