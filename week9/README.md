# Week 9 — Embedding + Vector Search（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 9 工作区，对应知识库笔记：
`01-Projects/AI-Agent/24周学习计划/Week-09-Embedding-Vector-Search`。

本周进入 **Phase 3：RAG + Memory（Week 9–12）** 的首个核心主题：**Embedding + Vector Search**。
系统性掌握文本向量化嵌入的数学与工程原理、文本分块（Chunking）的权衡策略、余弦相似度与距离度量、元数据过滤（Metadata Filtering），以及工业级向量数据库（PostgreSQL + pgvector）的检索实现。

---

## 本周覆盖情况与验收标准对照

| 验收标准 / 核心任务 | 是否覆盖 | 实现与载体 |
|---|---|---|
| 深入解释 Embedding 与向量检索原理 | ✅ | `vector-search-lab/README.md` 与 CLI `vector-search-lab explain` |
| 余弦相似度、余弦距离、欧氏距离与点积实现 | ✅ | `vector_search_lab/math_utils.py`（提供纯 Python 精确数学公式与单元测试） |
| 生产级 Markdown 分块器（保留标题层级与 overlap） | ✅ | `vector_search_lab/chunker.py`（`MarkdownChunker`） |
| 包含完整可运行的端到端范例与 CLI | ✅ | `vector-search-demo`、`vector-search-lab demo`、`vector-search-lab search` |
| 真实 HomeLab / OpenWrt 运维场景离线数据集 | ✅ | `vector-search-lab/data/` 目录下 4 份真实场景 Markdown 文档 |
| 向量存储抽象与元数据过滤 | ✅ | `vector_search_lab/vector_store.py`（`InMemoryVectorStore` + `PgVectorStore`） |
| PostgreSQL + pgvector 生产建表、HNSW 索引与查询 SQL 生成 | ✅ | `PgVectorStore.generate_schema_sql()` 与 `generate_search_sql()` |
| 完备的单元测试与端到端集成测试套件 | ✅ | `tests/` 目录下 29 个 pytest 用例全部通过 |

---

## 目录结构

```text
week9/
├── README.md                   # 本文件：Week 9 概览与验收总览
└── vector-search-lab/          # 可运行工程项目（详见其内部 README）
    ├── pyproject.toml          # 依赖管理 (pydantic>=2.10, pytest>=8)
    ├── .python-version         # Python 3.12
    ├── README.md               # 详尽的理论推导、参数权衡、pgvector 实操手册
    ├── data/                   # HomeLab & OpenWrt 运维知识切片样例
    │   ├── openwrt_ubus_guide.md
    │   ├── openwrt_firewall_setup.md
    │   ├── esxi_storage_management.md
    │   └── docker_homelab_services.md
    ├── src/vector_search_lab/
    │   ├── models.py           # Document, Chunk, SearchResult 数据模型
    │   ├── math_utils.py       # 余弦相似度、余弦距离、向量归一化
    │   ├── chunker.py          # Markdown 标题上下文感知的滑动窗口切分器
    │   ├── embeddings.py       # 确定性离线特征投影向量化与 OpenAI 适配器
    │   ├── vector_store.py     # 内存向量库与 PostgreSQL+pgvector DDL 生成器
    │   ├── pipeline.py         # 摄取、分块、向量化与检索全流程流水线
    │   └── cli.py              # demo, explain, search 命令行接口
    └── tests/                  # 自动化测试套件（29 个用例）
        ├── test_math_utils.py
        ├── test_chunker.py
        ├── test_embeddings.py
        ├── test_vector_store.py
        └── test_pipeline.py
```

---

## 快速运行

```powershell
cd C:\Users\zhangb8\mywork\ai-agent-24weeks\week9\vector-search-lab

# 1. 安装依赖环境
uv sync

# 2. 运行自动化测试
uv run pytest -v

# 3. 运行端到端检索演示
uv run vector-search-demo

# 4. 体验元数据过滤检索
uv run vector-search-lab search "端口转发" --category openwrt
```

---

## 一句话总结

Embedding 赋予文本"可计算的几何语义"，Chunking 决定了语义切片的"粒度与专注度"，Cosine Similarity 衡量了语义夹角的"同向程度"，而 Metadata Filtering 则将"软性语义匹配"与"硬性业务约束"完美融合。
通过内存向量库与 PostgreSQL pgvector 的对照实现，本周完成了从无状态 Agent 到具备外部检索记忆能力（RAG）的关键基石搭建。
