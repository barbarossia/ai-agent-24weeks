# Week 10 — Production RAG（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 10 工作区，对应知识库笔记：
`01-Projects/AI-Agent/24周学习计划/Week-10-Production-RAG`。

本周进入 **Phase 3：RAG + Memory（Week 9–12）** 的核心主题：**Production RAG**。
重点不再是"能不能检索"，而是"**怎么用数据证明检索质量**"：在同一份语料、同一批
chunk、同一组带标准答案的问题上，比较 **Vector Only / Keyword(BM25) / Hybrid**，
并用**可复现的文档级 Hit@k** 给出结论，而不是靠"感觉"。

配套可运行工程：[`production-rag-lab/`](production-rag-lab/README.md)
（Python 3.12 + `uv`，**完全离线**，无需 API Key、无需联网）。

---

## 本周覆盖情况与验收标准对照

| 验收标准 / 核心任务 | 是否覆盖 | 实现与载体 |
|---|---|---|
| 理解 BM25（tf / idf / 长度归一 / k1 / b） | ✅ | `production_rag_lab/lexical.py`（`BM25Index`）+ CLI `production-rag-lab explain` |
| 中英混合分词（分词权衡） | ✅ | `lexical.py`（`tokenize`，契约 `week10-mixed-cjk-v1`）+ `tests/test_tokenizer.py` |
| 语义检索（dense retrieval） | ✅ | 复用 Week 9 `MockEmbeddingProvider`，经 `retrieval.py` 的 `VectorAdapter` 适配 |
| 混合检索（Hybrid / RRF） | ✅ | `fusion.py`（RRF，`c=60`），**绝不相加 BM25 与 cosine 原始分数** |
| 重排序（Reranking） | ✅ | `rerank.py`：有界确定性 top-10 规则重排，**与 base hybrid 分开汇报** |
| Query Rewrite（讲解，不实现代码） | ✅（讲解） | lab README §4 与 `explain` 输出第 5 节：属笔记级主题，离线实验不实现 |
| Context Compression（讲解，不实现代码） | ✅（讲解） | lab README §4 与 `explain` 输出第 6 节：属笔记级主题，离线实验不实现 |
| 20–50 条带标准答案的问题集 | ✅ | `production-rag-lab/data/eval_queries.jsonl`，**24 条**，`gold_doc_ids` 为文档 ID |
| 文档级 Hit@k 评测器 | ✅ | `evaluation.py`：chunk 排序 → 去重折叠为唯一文档 → `k` 计唯一文档 → 宏平均 |
| 可运行 CLI 与端到端入口 | ✅ | `production-rag-lab demo / search / eval / explain` |
| 完备的离线自动化测试 | ✅ | `production-rag-lab/tests/`，**210 个用例全部通过**（2026-09-27） |

---

## 目录结构

```text
week10/
├── README.md                        # 本文件：Week 10 概览与验收总览
└── production-rag-lab/              # 可运行工程项目（详见其内部 README）
    ├── pyproject.toml               # 依赖管理（Week 9 本地可编辑依赖 + pytest）
    ├── .python-version              # Python 3.12
    ├── uv.lock                      # 本地 lockfile
    ├── data/eval_queries.jsonl      # 24 条固定带标准答案的评测问题
    ├── src/production_rag_lab/
    │   ├── paths.py                 # 默认语料目录与查询集位置
    │   ├── lexical.py               # 中英混合分词器 + BM25 索引 + 逐词解释
    │   ├── fusion.py                # RRF 融合（c=60）与确定性排序
    │   ├── rerank.py                # 有界确定性 top-10 规则重排
    │   ├── retrieval.py             # 语料加载、向量适配器、检索编排
    │   ├── evaluation.py            # JSONL 校验、文档折叠、Hit@k
    │   └── cli.py                   # demo, search, eval, explain 命令行
    └── tests/                       # 210 个离线测试用例
        ├── test_tokenizer.py        ├── test_cli.py
        ├── test_bm25.py             └── test_end_to_end.py
        ├── test_vector_adapter.py
        ├── test_fusion.py
        ├── test_rerank.py
        └── test_evaluation.py
```

**Week 9 复用方式**：`week10/production-rag-lab` 通过 **uv 本地可编辑路径依赖**
引用 `week9/vector-search-lab`，只使用其**公开 API**，**不复制、不修改任何 Week 9
文件**。语料即 Week 9 的只读样例语料（4 篇文档 → 17 个 chunk），因此三种方法
排序的是**同一批 chunk 对象**。

---

## 快速运行

```bash
cd week10/production-rag-lab

# 1. 安装环境（首次需要网络解析依赖；装好后运行时完全离线）
uv sync

# 2. 运行自动化测试
uv run pytest -v

# 3. 端到端演示：四种模式对比同一条查询
uv run production-rag-lab demo

# 4. 单次检索（可加 --explain 查看分数来源）
uv run production-rag-lab search "OpenWrt 端口转发 DNAT" --method hybrid --top-k 3 --explain
uv run production-rag-lab search "OpenWrt 端口转发 DNAT" --method hybrid --rerank rules --top-k 3

# 5. 文档级 Hit@k 评测（24 条固定问题）
uv run production-rag-lab eval --k 1,3
```

> Windows PowerShell 同样适用；所有命令均在 `week10/production-rag-lab` 目录下执行。

---

## 实测结果（2026-09-27）

语料 `week9/vector-search-lab/data`（4 文档 / 17 chunk），查询集
`data/eval_queries.jsonl`（24 条，sha256 `b10fec27…1e7f2`），分词器
`week10-mixed-cjk-v1`，`k1=1.5`、`b=0.75`、`c=60`。

| 方法 | Hit@1 | Hit@3 |
|---|---|---|
| `vector`（Week 9 mock embedder） | 0.7500（18/24） | 1.0000（24/24） |
| `bm25` | 1.0000（24/24） | 1.0000（24/24） |
| `hybrid`（RRF） | 1.0000（24/24） | 1.0000（24/24） |
| `hybrid+rules`（规则重排，单独汇报） | 0.9583（23/24） | 1.0000（24/24） |

**必须一起读的限定条件：**

1. **这不是 benchmark。** 4 篇手写文档 + mock embedder，只能演示检索机制。
2. **Hit@3 在此几乎无区分度。** 语料仅 4 篇文档，Hit@3 只有金标文档排到第 4 位时
   才会失败；真正有信息量的是 **Hit@1**。
3. **BM25 满分不代表"关键词检索更好"。** 金标指向的就是含有所查标识符的那篇文档，
   精确词面重叠在这份语料上是异常强的信号。`vector` 漏掉的 q12 / q14 / q16 / q19
   全是**低词汇重叠的同义改写**——这正是真实语义模型应当覆盖、而 mock 无法覆盖的
   场景。
4. **确定性规则重排实测没有带来提升**：`hybrid+rules` 在 q08 的 Hit@1 上由命中变为
   未命中。设计在评分前已固定，**未因结果回头修改**，此处如实记录。
5. **代码与文档中不存在任何质量阈值断言**，也没有任何测试断言 "hybrid 必须胜出"。

---

## 一句话总结

**BM25 靠词面、向量靠语义、RRF 靠排名把它们缝在一起、重排再精修候选；真正决定 RAG
能不能上生产的，不是模型选型，而是有没有一套固定语料 + 固定标准答案 + 可复现指标的
评测回路。** 本周用 24 条带金标的问题把这条回路跑通，并如实记录了"重排不一定有帮助"
这种不舒服但真实的结论。
