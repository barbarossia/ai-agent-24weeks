# Week 3 — LLM API Fundamentals（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 3 工作区，对应笔记：
`01-Projects/AI-Agent/24周学习计划/Week-03-LLM-API基础`。

> 本目录由 Implementor（handoff H001）在**发现目录原本不存在**后创建。
> 目标目录 `~/ai-agent-24weeks/week3/` 在本次执行前不存在，因此本目录内容
> 均为新增，未覆盖任何既有用户文件。
>
> 本周刻意**不依赖 Agent Framework**，也**不调用真实模型 API**：全部用
> mock / fake transport 在本地确定性运行，无需 API key，不产生费用。

---

## 本周覆盖情况（对照课程大纲）

| 大纲要求 | 本目录是否覆盖 | 载体 |
|---|---|---|
| Message roles | ✅ | `llm-api-lab/src/llm_api_lab/messages.py`（`Role`/`Message`/`Conversation` 顺序校验） |
| Token / Context Window | ✅ | `messages.py`（`estimate_tokens` + `ContextWindow.ensure_fits`） |
| Reasoning | ✅ | `models.ModelConfig.reasoning_effort` + `ChatResponse.reasoning` 透传 |
| Streaming | ✅ | `MockProvider.stream` / `OpenAICompatProvider.stream`（SSE）/ `cli stream` |
| Structured Output | ✅ | `client.complete_structured`（JSON 提取 + Pydantic 校验 + 修复重试） |
| JSON Schema | ✅ | `schemas.describe_schema` / `json_response_format` / `cli schema` |
| Pydantic Schema | ✅ | `schemas.TriageResult`（`extra="forbid"`、枚举、范围约束） |
| 实战：Question → LLM → Structured JSON → Pydantic | ✅ | `cli demo`、`examples/01_structured_triage.py` |
| 文本输出 vs Structured Output | ✅ | `cli demo` 同时打印 raw 字符串与 validated 对象；笔记第 4 节 |
| 用 Schema 约束输出 | ✅ | `response_format=json_schema` + 提示词内嵌 schema |
| 处理 invalid output | ✅ | `StructuredOutputError` + `complete_structured(repair_attempts=...)` |
| 实现 streaming | ✅ | `LLMClient.stream` / `collect_stream` |
| 可靠性（超时/重试） | ✅ | `client.py`（`asyncio.wait_for` + 指数退避 + 429 `Retry-After`） |
| 费用/延迟可见 | ✅ | `usage.py` + `client.Completion`（token/latency/attempts/cost） |
| 安全边界 | ✅ | `transport.py`（无隐式凭据 / 无默认端点 / `Authorization` 安全默认） |

### 尚未覆盖（留作练习，见 `llm-api-lab/README.md` 文末）

- 真实厂商 SDK / 真实端点调用（本周刻意只用 mock 与 `httpx.MockTransport`）
- 流式过程中重试（已产出 token 后重试会重复内容）
- 精确 tokenizer（`tiktoken`）与真实价目表
- 历史裁剪 / 摘要压缩（context pruning）
- 并发批量调用与整体限流（Week 2 `Semaphore` + 本周重试策略）

---

## 目录结构

```text
week3/
├── README.md                          # 本文件：Week 3 总览
├── llm-api-lab/                       # 可运行项目（见其 README）
│   ├── pyproject.toml                 # pydantic + httpx
│   ├── uv.lock
│   ├── .python-version                # Python 3.11
│   ├── README.md                      # 详细讲解 + 运行 + 练习
│   ├── examples/                      # 4 个独立示例
│   │   ├── 01_structured_triage.py
│   │   ├── 02_streaming_tokens.py
│   │   ├── 03_retry_and_errors.py
│   │   └── 04_http_transport.py
│   ├── src/llm_api_lab/
│   │   ├── errors.py                  # 异常树：可重试 / 不可重试
│   │   ├── messages.py                # 角色 / token / 上下文窗口
│   │   ├── models.py                  # 线缆层请求/响应 + ModelConfig
│   │   ├── usage.py                   # token → 成本
│   │   ├── schemas.py                 # TriageResult + JSON Schema
│   │   ├── providers.py               # Provider 协议 + mock / scripted
│   │   ├── transport.py               # OpenAI 兼容 HTTP + SSE
│   │   ├── client.py                  # 超时/重试/结构化/计费
│   │   └── cli.py                     # 6 个演示命令
│   └── tests/                         # 74 个用例
└── notes/
    └── Week-03-LLM-API基础.md         # 交给 Knowledge 的笔记草稿副本
```

> Obsidian 笔记草稿的**权威副本**位于本 handoff 的
> `evidence/Week-03-LLM-API基础.md`；`notes/` 下只是同内容的工作副本，
> 便于在项目内直接阅读。正式 vault 笔记由 Knowledge 阶段写入。

---

## 快速开始

```bash
cd llm-api-lab
uv sync                       # 安装 Python 3.11 + 依赖
uv run pytest                 # 74 passed（成功 + 错误/边界路径）
uv run llm-api-lab demo       # 结构化输出 happy path
uv run llm-api-lab --help     # 全部 6 个演示命令
```

---

## 一句话总结

Week 1 教会"Pydantic 守边界"，Week 2 教会"async HTTP 与 SSE"；
Week 3 把两者合到模型 API 上：**模型只会返回字符串，而且可能超时、被限流、
返回坏 JSON**。于是我们建立四道防线 —— 异常树区分可重试性、`asyncio.wait_for`
管超时、退避重试管暂时性故障、Pydantic 校验管结构化输出 —— 并用
`Provider` 协议把"策略"与"传输"彻底分开，让所有坏路径都能在本地确定性复现。

下一周（Week 4）的 Tool Calling，本质就是"结构化输出 + 工具执行"；
本周练熟的 `complete_structured` 与异常树会直接被复用。
