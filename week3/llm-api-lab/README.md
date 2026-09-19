# llm-api-lab — Week 3：LLM API Fundamentals

本目录是 24 周 AI Agent Engineer 学习计划的 Week 3 工作区项目，对应笔记：
`01-Projects/AI-Agent/24周学习计划/Week-03-LLM-API基础`。

> 本目录由 Implementor（handoff H001）在**发现 `~/ai-agent-24weeks/week3/` 原本不存在**后创建。
> 目标目录在本次执行前不存在，因此本目录内容均为新增，未覆盖任何既有用户文件。
> 参考了 Week 1（`ai-agent-lab`）与 Week 2（`homelab-api`）的约定：uv + Python 3.11 +
> Pydantic 守边界 + pytest 保护行为 + 中文讲解。

---

## 本周解决什么问题

Week 1 学会了用 Pydantic 守住"不可信输入"的边界；Week 2 学会了 async HTTP 与 API 服务。
Week 3 把两者合起来，直接面对一个**不可信、要花钱、会超时、还会返回非结构化文本**的外部模型：

```text
User Question
     ↓
   LLM            ← 只会返回字符串，可能超时 / 429 / 5xx / 返回坏 JSON
     ↓
Structured JSON  ← 用 JSON Schema 约束它，但绝不盲信
     ↓
Pydantic Validation  ← 最后一道闸门；失败就修复重试或拒绝
```

**总原则（大纲要求）：这一周不依赖任何 Agent Framework。** 先把裸 API 的输入、输出、
约束机制摸清楚，Week 4 才谈 tool calling。

---

## 覆盖情况（对照大纲）

| 大纲要求 | 是否覆盖 | 载体 |
|---|---|---|
| Message roles | ✅ | `messages.py`（`Role` / `Message` / `Conversation` 顺序校验） |
| Token / Context Window | ✅ | `messages.py`（`estimate_tokens`、`ContextWindow.ensure_fits`） |
| Reasoning | ✅ | `models.py` 的 `reasoning_effort` 配置与 `ChatResponse.reasoning` 透传 + README 第 3 节 |
| Streaming | ✅ | `MockProvider.stream` / `OpenAICompatProvider.stream`（SSE 解析）/ `cli stream` |
| Structured Output | ✅ | `client.complete_structured`（JSON 提取 + Pydantic 校验 + 修复重试） |
| JSON Schema | ✅ | `schemas.describe_schema` / `json_response_format` / `cli schema` |
| Pydantic Schema | ✅ | `schemas.TriageResult`（`extra="forbid"`、枚举、范围约束） |
| 实战：Question → LLM → JSON → Pydantic | ✅ | `cli demo`、`examples/01_structured_triage.py` |
| 理解文本输出 vs Structured Output | ✅ | README 第 3 节；`cli demo` 同时打印 raw 字符串与 validated 对象 |
| 能用 Schema 约束输出 | ✅ | `response_format=json_schema` + 提示词内嵌 schema |
| 能处理 invalid output | ✅ | `StructuredOutputError` + `complete_structured(repair_attempts=...)` |
| 能实现 streaming | ✅ | `LLMClient.stream` / `collect_stream` |

### 尚未覆盖（留作练习，见文末）

- 真实厂商 SDK / 真实端点调用（本周刻意只用 mock 与 `httpx.MockTransport`）
- 流式过程中的重试（一旦已产出 token，重试会重复内容）
- 精确 tokenizer（`tiktoken`）与真实价目表
- 历史裁剪 / 摘要压缩（context pruning）
- 并发批量调用与整体限流（Week 2 的 `Semaphore` + 本周的重试策略结合）

---

## 架构：策略与传输分离

```text
                    ┌──────────── LLMClient（策略层 client.py）────────────┐
                    │ 上下文预算 · 超时 wait_for · 退避重试 · 结构化校验 · 计费 │
                    └───────────────────────┬─────────────────────────────┘
                                            │ 依赖 Provider 协议（而非 httpx）
                    ┌───────────────────────▼─────────────────────────────┐
                    │ Provider（传输层 providers.py / transport.py）        │
                    │  MockProvider    确定性关键词分诊（默认，零依赖）        │
                    │  ScriptedProvider 脚本回放：文本/异常/延迟（测试坏路径）  │
                    │  OpenAICompatProvider 真实 HTTP + SSE（测试用假 transport）│
                    └─────────────────────────────────────────────────────┘
```

三层都返回**同一种** `ChatResponse`，所以换 provider 时上层策略代码一行不改。
这也是为什么测试可以用 `ScriptedProvider` 精确制造 429 / 5xx / 坏 JSON / 超时，
而不用碰网络。

### 目录结构

```text
llm-api-lab/
├── pyproject.toml            # pydantic + httpx；pytest 配置
├── uv.lock                   # 依赖锁定 → 可复现
├── .python-version           # Python 3.11
├── README.md                 # 本文件：详细讲解 + 运行 + 练习
├── examples/
│   ├── 01_structured_triage.py   # Question → JSON → Pydantic
│   ├── 02_streaming_tokens.py    # 流式增量
│   ├── 03_retry_and_errors.py    # 429/503 重试 vs 401 不重试
│   └── 04_http_transport.py      # httpx.MockTransport 下的真实传输路径
├── src/llm_api_lab/
│   ├── __init__.py
│   ├── __main__.py           # python -m llm_api_lab
│   ├── cli.py                # 6 个可观察的演示命令
│   ├── errors.py             # 异常树：可重试 / 不可重试
│   ├── messages.py           # Role / Message / Conversation / token / 上下文窗口
│   ├── models.py             # 线缆层：ModelConfig / ChatRequest / ChatResponse / Usage
│   ├── usage.py              # token → 成本估算
│   ├── schemas.py            # TriageResult + JSON Schema 渲染
│   ├── providers.py          # Provider 协议 + MockProvider + ScriptedProvider
│   ├── transport.py          # OpenAICompatProvider + SSE 解析
│   └── client.py             # LLMClient：超时/重试/结构化/计费
└── tests/                    # 见下表
```

---

## 核心概念（每个都能在代码里指出来）

### 1. Message roles（`messages.py`）

| 角色 | 作用 | 约束 |
|---|---|---|
| `system` | 设定模型行为、放 schema/规则 | 只能第 0 条，最多 1 条 |
| `user` | 用户输入 | 最后一条不能是 system |
| `assistant` | 模型历史回复（含被修复的坏输出） | 修复重试时会把坏输出回灌 |
| `tool` | 工具执行结果 | Week 4 才真正用到 |

这些约束不是教条，而是 API 契约：把它们写进 `model_validator`，错误在**构造对话时**就暴露，
而不是发出去等 400。

### 2. Token / Context Window（`messages.py`）

模型按 token 计费、按 token 限长。本周不去拉真实 tokenizer，而是提供一个**可解释的近似**：

```python
estimate_tokens("hello")      # ASCII：约 4 字符 1 token
estimate_tokens("网络抖动")    # CJK：约 1 字符 1 token
```

`ContextWindow(max_context_tokens, reserved_output_tokens)` 计算
`available_input_tokens = 总数 - 输出预留`，`ensure_fits()` 在**发送前**拒绝超限请求。
`cli budget` 会演示这一点：提前拒绝，而不是发出去等 400、等账单。

> 真实计费必须用官方 tokenizer。这里的估算只用于教学和预算护栏，**不要用于精确账单**。

### 3. Reasoning 与模型配置（`models.py`）

`ModelConfig` 把 `temperature / max_output_tokens / timeout_s / reasoning_effort` 集中管理。
`reasoning_effort` 是推理模型"思维链预算"的配置位；推理过程（如厂商返回
`reasoning_content`）通过 `ChatResponse.reasoning` 透传。**mock 会忽略这些参数——
这正是 mock 与真实的差异之一**：mock 不会真的"思考"，也不会改变成本曲线。

### 4. Structured Output：JSON Schema + Pydantic（`schemas.py` / `client.py`）

- 提示词里嵌入 `TriageResult.model_json_schema()`；
- `response_format={"type":"json_schema", ...}` 做服务端约束（厂商支持度不一）；
- **无论厂商多自信，本地都要再 `model_validate` 一次**——模型输出永远是不可信输入；
- `StructuredOutputError` 同时携带 `raw_text`、`reason`（`invalid_json` / `schema_mismatch`）
  和 `validation_errors`，让"修复重试"有据可依。

### 5. Invalid output 的处理（`client.complete_structured`）

```text
第 1 次输出坏 JSON
      ↓ 解析/校验失败
把坏输出作为 assistant 消息回灌 + 追加 user 纠正指令
      ↓
第 2 次输出合法 JSON → Pydantic 通过
```

`repairs` 字段告诉你修复了几次；`Usage` 会**累加所有尝试**的 token——因为修复是要花钱的。
`repair_attempts=0` 表示不修复、直接失败（对延迟敏感的调用适合这种策略）。

### 6. Streaming（`client.stream` / `transport.stream`）

流式改善的是**首字延迟**（time-to-first-token），总量与费用不变。
`transport.py` 里的 SSE 解析处理了 `data: {...}`、注释行、空行、坏 JSON 与 `data: [DONE]`。
注意：一旦开始产出 token 就不适合中途重试（会重复内容），这是后续话题。

### 7. 超时与重试（`client.py` / `errors.py`）

异常树按**可重试性**分叉：

| 异常 | 触发 | 是否重试 |
|---|---|---|
| `LlmTimeoutError` | `asyncio.wait_for` 超时 | ✅ |
| `LlmConnectionError` | DNS/TLS/连接失败 | ✅ |
| `LlmRateLimitError` | HTTP 429 | ✅（优先用 `Retry-After`） |
| `LlmServerError` | HTTP 5xx | ✅（指数退避） |
| `LlmAuthError` | HTTP 401/403 | ❌ |
| `LlmClientError` | HTTP 400/404/422 | ❌ |

只看退出码/状态码不够，**必须知道"这个错能不能重试"**：对 401 做三次退避重试，
只会白等、白烧配额。

### 8. 费用与延迟（`usage.py` / `client.Completion`）

每次补全都返回 `usage`（prompt/completion/total token）、`latency_ms`、`attempts`、
`cost_usd`。价格表是**可注入的示意值**，真实项目应以官方价目表为准。
把成本放进返回值，是让"约束可见"的第一步。

### 9. 安全边界（`transport.py`）

- 构造 `OpenAICompatProvider` **必须显式**给 `base_url`，没有隐式默认端点；
- **绝不读取** `os.environ` 或任何隐式凭据；不传 `api_key` 就不发送 `Authorization` 头；
- 异常消息不回显 key；`.gitignore` 默认忽略 `.env` 与 `*credentials*`；
- 本仓库全部测试/示例使用 mock 或 `httpx.MockTransport`，**不联网、不产生费用**。

### 10. 真实 API 与 mock 的差异

| 维度 | mock / scripted | 真实 API |
|---|---|---|
| 输出 | 确定性 | 非确定性（temperature、模型版本漂移） |
| 失败 | 按脚本精确制造 | 随机、偶发、与负载相关 |
| 用量 | 近似估算 | 服务端精确返回 |
| 成本 | 0 | 按 token 计费，输出通常更贵 |
| reasoning | 忽略配置 | 影响延迟、成本与输出质量 |
| 安全 | 无凭据 | 必须有 key，且 key 是最敏感的资产 |

mock 的价值是**让失败路径可重复**；它不能替代对真实非确定性的观测。

---

## 快速开始

```bash
cd week3/llm-api-lab
uv sync                 # 安装 Python 3.11 + pydantic/httpx/pytest
uv run pytest           # 全部测试（成功 + 错误/边界路径）
```

### 命令行演示（全部无需 API key、不联网）

```bash
uv run llm-api-lab demo          # 结构化输出 happy path
uv run llm-api-lab schema        # TriageResult 的 JSON Schema
uv run llm-api-lab invalid-json  # 坏 JSON → 修复重试 → 通过
uv run llm-api-lab retry         # 429/503 退避重试（sleeper 记录，不真等待）
uv run llm-api-lab stream        # 流式逐片输出
uv run llm-api-lab budget        # 上下文窗口超限，提前拒绝
```

### 独立示例

```bash
uv run python examples/01_structured_triage.py
uv run python examples/02_streaming_tokens.py
uv run python examples/03_retry_and_errors.py
uv run python examples/04_http_transport.py
```

---

## 实测证据

见本 handoff 的 `result.md` 与 `evidence/`（命令、输出、测试计数）。
下方由 Implementor 在本机运行后填入：

| 场景 | 命令 | 预期 |
|---|---|---|
| 全部测试 | `uv run pytest` | 全绿（成功 + 错误/边界） |
| 结构化 happy path | `uv run llm-api-lab demo` | raw 是字符串，validated 是对象，repairs=0 |
| 坏 JSON 修复 | `uv run llm-api-lab invalid-json` | provider 调用 2 次，repairs=1 |
| 退避重试 | `uv run llm-api-lab retry` | attempts=3，delays=[0.2, 0.2] |
| 流式 | `uv run llm-api-lab stream` | 多片 delta + 拼回完整 JSON |
| 预算保护 | `uv run llm-api-lab budget` | 发送前抛 `ContextWindowExceededError` |

---

## 练习（建议按顺序做）

1. **坏路径观察**：把 `complete_structured(repair_attempts=1)` 改成 `0`，
   跑 `invalid-json` 场景，观察异常与 `raw_text`。
2. **重试预算**：给 `RetryPolicy` 加 `max_total_delay_s`，超过就放弃（防止退避叠加成分钟级）。
3. **流式重试**：设计"仅在首个 token 之前可重试"的流式调用，并写测试。
4. **历史裁剪**：对话超窗时，从最旧的非 system 消息开始丢弃，直到放得下，并记录丢弃条数。
5. **精确 tokenizer**：接入 `tiktoken`，对比估算器与真实值的偏差。
6. **供应商差异**：给 `OpenAICompatProvider` 加一个 `AnthropicMessagesProvider`，复用同一 `Provider` 协议。
7. **成本护栏**：在 `LLMClient` 上累计会话成本，超过阈值时拒绝继续调用。
8. **可观测性**：给每次调用生成 `request_id`，记录 model/tokens/latency/attempts（**不记录原文，可能含敏感信息**）。

---

## 与前后周的连接

- **接 Week 2**：`httpx.AsyncClient` + SSE 的心智模型直接复用；本周把 HTTP 细节收敛到
  `Provider` 协议之后，Week 4 的 tool calling 只需在 `client.py` 上再加一层。
- **向 Week 4**：Tool Calling 的本质是"结构化输出 + 一个特殊的 `tool_calls` 字段 +
  本地执行工具"。本周把"结构化输出 + 校验 + 修复"练熟，Week 4 会顺很多。
