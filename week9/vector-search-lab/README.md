# Week 9 — Embedding + Vector Search Lab

Week 9 — Embedding + Vector Search：深入理解向量嵌入（Embeddings）、相似度度量（Cosine Similarity）、文本分块策略（Chunking）、元数据过滤（Metadata Filtering）以及向量数据库（PostgreSQL + pgvector）的检索全流程。

---

## 核心概念与工程原理

### 1. 什么是向量嵌入（Embedding）？
向量嵌入是将非结构化文本映射到连续高维几何空间（$\mathbb{R}^d$，如 128 维、384 维、1536 维）的致密实数向量。
- **与传统稀疏检索（TF-IDF / BM25）的区别**：
  - BM25 依赖字词的字面完全匹配（Exact Match），缺乏泛化能力；若查询词与文档字面无重合（如"重启路由器" vs "重新引导网络网关"），BM25 检索得分直接为 0。
  - Dense Embedding 将语义压缩进高维空间，语义相近的句子即便字面完全不同，也会映射到欧氏空间中夹角极小、彼此极其靠近的向量点上。

### 2. 向量相似度与距离度量（Similarity & Distance）
给定高维向量 $u, v \in \mathbb{R}^d$：

1. **余弦相似度（Cosine Similarity）**：
   $$\text{cosine\_similarity}(u, v) = \frac{u \cdot v}{\|u\|_2 \|v\|_2} = \frac{\sum_{i=1}^d u_i v_i}{\sqrt{\sum_{i=1}^d u_i^2} \sqrt{\sum_{i=1}^d v_i^2}}$$
   - 取值范围：$[-1.0, 1.0]$。$1.0$ 表示完全同向（语义高度重合），$0.0$ 表示正交无关，$-1.0$ 表示方向完全相反。
   - **核心特征**：只关注向量之间的夹角方向，不受向量绝对模长/尺度的影响。这是文本语义检索的首选度量。

2. **余弦距离（Cosine Distance）**：
   $$\text{cosine\_distance}(u, v) = 1.0 - \text{cosine\_similarity}(u, v)$$
   - 取值范围：$[0.0, 2.0]$。$0.0$ 表示方向完全一致，值越小表示越相似。
   - PostgreSQL `pgvector` 中使用 `<=>` 操作符进行余弦距离排序（`ORDER BY embedding <=> query_vector ASC`）。

3. **欧氏距离（Euclidean Distance / $L_2$）**：
   $$d(u, v) = \sqrt{\sum_{i=1}^d (u_i - v_i)^2}$$
   - `pgvector` 中对应 `<->` 操作符。
   - **关键工程性质**：当所有向量均预先进行了 $L_2$ 单位归一化（$\|u\|_2 = \|v\|_2 = 1.0$）后，$L_2^2 = 2 - 2(u \cdot v) = 2 - 2 \cdot \text{cosine\_similarity}$。此时，欧氏距离与余弦相似度的排序**完全等价**。

4. **点积 / 内积（Dot Product / Inner Product）**：
   $$u \cdot v = \sum_{i=1}^d u_i v_i$$
   - `pgvector` 中对应 `<#>` 操作符（负内积，用于 ASC 升序索引检索）。
   - 单位归一化后，点积直接等于余弦相似度，计算开销最低，现代 CPU/GPU 可利用 SIMD 指令进行极速并行点积运算。

---

### 3. 文档分块（Chunking）的权衡考量

为什么不能把整篇运维文档直接喂给模型做 Embedding？
1. **模型输入上限**：主流 Embedding 模型（如 `text-embedding-3-small` 为 8192 tokens，小型本地模型多为 512 tokens）有硬性截断长度。
2. **语义稀释（Semantic Dilution）**：若将一份 30 页的运维手册整体压进一个向量，这个向量会沦为所有主题的"平均值"，丧失了对具体某条命令或排错步骤的敏锐度（"大海捞针"失效）。
3. **检索精准度与 Token 成本**：RAG 场景下将最相关的 2~3 个精炼片段（每个 300 字符）注入 Prompt，不仅大幅节省上下文窗口消耗，还能避免模型产生幻觉。

#### 分块尺寸（Chunk Size）与重叠长度（Chunk Overlap）的权衡：
- **Chunk Size 过小**（如 50 字符）：句子被腰斩，上下文严重缺失，连指代代词（"它"、"该参数"）都无法还原。
- **Chunk Size 过大**（如 2000 字符）：多个独立问题被混合，检索相关度评分被稀释。
- **Chunk Overlap（通常建议 10% ~ 20%）**：相邻 chunk 之间保留重叠区间，防止关键配置语法、长代码块或排错条件因恰好处于分块切割边界而被截断丢失。
- **Markdown 标题层级保留（Heading Breadcrumbs）**：本实验的 `MarkdownChunker` 会自动解析 `#`、`##` 等标题，为每个切片附带上下文路径（如 `[OpenWrt 防火墙配置手册 > 端口转发（DNAT）]`），防止孤立文本片段脱离上下文语义。

---

### 4. 向量检索索引：Flat、IVFFlat 与 HNSW 对比

| 索引类型 | 算法原理 | 查询复杂度 | 召回率 (Recall) | 索引构建耗时与内存 | 适用场景 |
|---|---|---|---|---|---|
| **Flat (暴力精确)** | 遍历所有向量计算距离 | $O(N \cdot d)$ | **100% (理论真值)** | 无需构建索引，内存极小 | 小于 5 万条向量、离线单元测试 |
| **IVFFlat (倒排文件)** | K-Means 聚类，划分 Voronoi 蜂窝单元，检索时仅探查临近聚类中心 | $O(\frac{N}{\text{lists}} \cdot \text{probes} \cdot d)$ | 85% ~ 95% | 构建较快，内存较低 | 百万级中等规模，写入频繁 |
| **HNSW (分层小世界图)** | 多层跳表式邻近图导航 | $O(\log N)$ | **> 98%** | 构建较慢，需要额外内存构建图 | **生产环境推荐**，高性能低延迟检索 |

---

### 5. 元数据过滤（Metadata Filtering）策略

在生产环境中，纯向量语义检索无法解决精确业务限定（如"只查询 OpenWrt 相关的配置"或"只要发布时间在 2026 年以后的文档"）：
1. **Pre-filtering（前置过滤）**：先按元数据（如 `category = 'openwrt'`）筛选出目标候选集合，再在子集内计算向量相似度。
2. **Post-filtering（后置过滤）**：先向量检索出 Top-100，再遍历剔除不满足元数据的项。（缺点：若目标类目占比稀少，可能导致 Top-100 过滤后剩余有效结果为 0）。
3. **Single-Stage / Iterative Search（pgvector 0.5.0+ 引擎原生支持）**：在 HNSW 图遍历过程中即时结合 SQL `WHERE` 条件评估，兼顾高检索速度与高召回率。

---

## 项目架构与代码结构

```text
week9/vector-search-lab/
├── pyproject.toml              # 项目依赖 (pydantic>=2.10, pytest>=8)
├── .python-version             # Python 3.12
├── README.md                   # 本文档：理论讲解 + 运行命令 + 验证记录
├── data/                       # 离线 HomeLab / OpenWrt 真实场景 Markdown 文档
│   ├── openwrt_ubus_guide.md        # ubus-over-HTTP 架构与只读接口白名单
│   ├── openwrt_firewall_setup.md    # nftables 区域划分、端口转发 DNAT 与 NAT 环回
│   ├── esxi_storage_management.md   # VMFS 数据存储、快照膨胀告警与清理
│   └── docker_homelab_services.md   # Docker compose 服务矩阵、网络隔离与健康检查
├── src/vector_search_lab/
│   ├── __init__.py             # 核心组件导出
│   ├── __main__.py             # python -m vector_search_lab 入口
│   ├── models.py               # Pydantic 领域模型 (Document, Chunk, SearchResult 等)
│   ├── math_utils.py           # 向量数学：余弦相似度、余弦距离、归一化、欧氏距离
│   ├── chunker.py              # Markdown 语义与滑动窗口分块器 (保留标题层级与 overlap)
│   ├── embeddings.py           # Mock 确定性离线向量化与 OpenAI REST 接入器
│   ├── vector_store.py         # InMemoryVectorStore 与 PgVectorStore (DDL/SQL 生成)
│   ├── pipeline.py             # 端到端摄取、切片、向量化与 Top-K 检索流水线
│   └── cli.py                  # CLI 工具 (demo / explain / search)
└── tests/
    ├── test_math_utils.py      # 10 个数学用例（正交/反向/同向/归一化/距离等）
    ├── test_chunker.py         # 5 个分块器用例（段落切分/overlap/标题路径/极短文本等）
    ├── test_embeddings.py      # 6 个向量化用例（确定性/维度/归一化/语义聚类等）
    ├── test_vector_store.py    # 6 个存储层用例（Top-k 排序/元数据过滤/pgvector DDL 生成等）
    └── test_pipeline.py        # 2 个端到端流水线集成用例（真实文档摄取与检索验证）
```

---

## 快速上手与运行命令

### 1. 安装与依赖同步
```powershell
cd C:\Users\zhangb8\mywork\ai-agent-24weeks\week9\vector-search-lab
uv sync
```

### 2. 运行自动化单元测试与集成测试
```powershell
uv run pytest -v
```

### 3. 运行端到端演示程序
```powershell
# 方式 1：通过注册的 console script
uv run vector-search-demo

# 方式 2：通过统一 CLI 入口
uv run vector-search-lab demo
```

### 4. 交互式命令行检索
```powershell
# 全局语义检索
uv run vector-search-lab search "如何配置端口转发"

# 带元数据分类过滤检索
uv run vector-search-lab search "网络配置与接口" --category docker

# 查看向量检索与 pgvector 架构原理解析
uv run vector-search-lab explain
```

---

## PostgreSQL + pgvector 生产环境部署实战

本实验室内置的 `PgVectorStore` 提供了生产级 DDL 与查询模板生成。在包含真实 PostgreSQL 的环境中，执行以下脚本即可快速接入：

### 1. 数据库建表与 HNSW 索引 SQL
```sql
-- 1. 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 创建切片与向量存储表（以 128 维或 1536 维为例）
CREATE TABLE IF NOT EXISTS homelab_document_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INT NOT NULL,
    title TEXT NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    source_file TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding vector(128) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 创建基于余弦距离的 HNSW 向量索引
CREATE INDEX IF NOT EXISTS homelab_chunks_hnsw_idx 
ON homelab_document_chunks 
USING hnsw (embedding vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

-- 4. 创建元数据 B-Tree 索引支持高效混合过滤
CREATE INDEX IF NOT EXISTS homelab_chunks_category_idx ON homelab_document_chunks (category);
CREATE INDEX IF NOT EXISTS homelab_chunks_doc_id_idx ON homelab_document_chunks (doc_id);
```

### 2. 向量相似度查询与元数据过滤 SQL
```sql
-- 查询与目标向量最相似的前 3 条切片，限定类目为 'openwrt'
SELECT
    chunk_id,
    title,
    heading,
    content,
    1.0 - (embedding <=> :query_vector) AS cosine_similarity
FROM homelab_document_chunks
WHERE category = 'openwrt'
ORDER BY embedding <=> :query_vector ASC
LIMIT 3;
```
