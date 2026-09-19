---
title: Week-03-LLM-API基础
type: learning-note
project: AI-Agent
week: 3
status: draft-for-knowledge
created: 2026-09-19
tags:
  - AI-Agent
  - Python
  - LLM
  - API
  - StructuredOutput
  - JSONSchema
  - learning-plan
source_task: LLM-api-week3-fundamentals
---

# Week 03 — LLM API Fundamentals

> 上一周：[[Week-02-Async-FastAPI]] | 下一周：[[Week-04-Function-Tool-Calling]]

> [!abstract] 本周一句话
> 模型 API 只会返回**字符串**：它还会超时、被限流、返回坏 JSON。本周在**不依赖任何
> Agent Framework**、**不调用真实 API** 的前提下，用 mock 把"消息模型 → 结构化输出
> → 校验 → 失败修复 → 重试"整条链路走通，建立四道防线：**异常树区分可重试性、
> wait_for 管超时、退避重试管暂时性故障、Pydantic 管不可信输出**。

## 目标

绕开 Agent Framework，直接理解模型 API 的输入、输出和约束机制，回答一个问题：
**"调用一次 LLM"到底牵扯多少工程问题？**

答案远超"发个 HTTP 请求"：消息角色与顺序、token 计费与上下文窗口、结构化输出的
约束与校验、streaming 的首字延迟、超时与重试、失败时的成本、以及凭据的安全边界。

## 学习内容

- Message roles（system / user / assistant / tool 及其顺序约束）
- Token / Context Window（估算、预算、超限提前拒绝）
- Reasoning（推理强度配置与思维链透传）
- Streaming（SSE、增量拼装、首字延迟）
- Structured Output（JSON Schema 约束 + Pydantic 本地校验）
- JSON Schema / Pydantic Schema（`model_json_schema()` 的双重角色）
- 可靠性：超时、指数退避、429 `Retry-After`、不可重试错误
- 工程约束：费用/延迟可见、凭据安全边界

## 实战产出

项目：**`llm-api-lab`** —— 把 `User Question → LLM → Structured JSON → Pydantic`
做成一条可运行、可测试、可观察的流水线，场景是 HomeLab 告警分诊。

```text
User Question
     ↓
   LLM           ← 只会返回字符串；可能超时 / 429 / 5xx / 坏 JSON
     ↓
Structured JSON  ← JSON Schema 约束（但绝不盲信）
     ↓
Pydantic Validation  ← 最后一道闸门：失败 → 修复重试 / 拒绝
     ↓
TriageResult { category, severity, action, confidence, reason }
```

工作区 `~/ai-agent-24weeks/week3/llm-api-lab/`：

```text
llm-api-lab/
├── pyproject.toml            # pydantic + httpx；pytest(asyncio auto)
├── uv.lock / .python-version # 可复现：Python 3.11
├── README.md                 # 详细讲解 + 运行 + 练习
├── examples/                 # 4 个独立示例（结构化 / 流式 / 重试 / HTTP 传输）
├── src/llm_api_lab/
│   ├── errors.py             # 异常树：RetryableError 分叉
│   ├── messages.py           # Role / Message / Conversation / token / ContextWindow
│   ├── models.py             # ModelConfig / ChatRequest / ChatResponse / Usage
│   ├── usage.py              # token → 成本
│   ├── schemas.py            # TriageResult + JSON Schema 渲染
│   ├── providers.py          # Provider 协议 + MockProvider + ScriptedProvider
│   ├── transport.py          # OpenAICompatProvider + SSE 解析
│   ├── client.py             # LLMClient：超时/重试/结构化/计费
│   └── cli.py                # 6 个演示命令
└── tests/                    # 74 个用例
```

### 架构：策略与传输分离

```text
LLMClient（策略：预算 · 超时 · 重试 · 结构化 · 计费）
     │
     ▼
Provider（传输：ChatRequest → ChatResponse）
   ├── MockProvider      确定性关键词分诊（默认，零依赖）
   ├── ScriptedProvider  脚本回放文本/异常/延迟（测试坏路径）
   └── OpenAICompatProvider  真实 HTTP + SSE（测试用 httpx.MockTransport）
```

三层都返回同一种 `ChatResponse`，换 provider 时上层策略代码一行不改 ——
这正是"依赖倒置"在 LLM 客户端的落地。

## 关键概念

### 1. Message roles：角色不是标签，是 API 契约

| 角色 | 作用 | 约束 |
|---|---|---|
| `system` | 设定行为、放 schema/规则 | 只能第 0 条，最多 1 条 |
| `user` | 用户输入 | 最后一条不能是 system |
| `assistant` | 模型历史回复（含被修复的坏输出） | 修复重试时会被回灌 |
| `tool` | 工具执行结果 | Week 4 才真正用到 |

把顺序约束写进 `model_validator`，错误在**构造对话时**就暴露，而不是发出去等 400。

### 2. Token / Context Window：把预算显式化

模型按 token 计费、按 token 限长。本周用**可解释的近似估算**（非真实 tokenizer）：

```python
estimate_tokens("abcd")      # ASCII：约 4 字符 1 token → 1
estimate_tokens("网络")       # CJK：约 1 字符 1 token → 2
```

`ContextWindow(max_context_tokens, reserved_output_tokens)` 预先扣掉输出预留，
`ensure_fits()` 在**发送前**拒绝超限请求。实测：64 token 窗口下，一段
"网络抖动 ×200" 被估算为 945 token > 可用 48 → 直接抛出
`ContextWindowExceededError`，而不是发出去等 400、等账单。

> 真实计费必须用官方 tokenizer（如 `tiktoken`）。估算器只用于教学与预算护栏。

### 3. Reasoning 与模型配置

`ModelConfig` 集中管理 `temperature / max_output_tokens / timeout_s / reasoning_effort`。
推理模型的思维链通过 `ChatResponse.reasoning` 透传（解析时兼容
`reasoning_content` / `reasoning` 两种字段名）。
**mock 会忽略这些参数** —— 这正是 mock 与真实的差异之一：mock 不会真的"思考"，
也不会因此改变延迟和成本曲线。

### 4. 文本输出 vs Structured Output

- **文本输出**：模型返回一段自然语言，下游只能再解析，脆弱且难测试；
- **Structured Output**：用 JSON Schema + `response_format` 约束形状，
  再用 Pydantic 在本地**再校验一次**。

关键认知：**厂商的 `json_schema` 支持度不一，而且再强的服务端约束也不能替代本地校验。**
模型输出永远属于"不可信输入"——这正是 Week 1 建立的 Pydantic 边界的用武之地。

```python
class TriageResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    category: TriageCategory
    severity: Severity
    action: str = Field(min_length=1, max_length=120)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=400)
```

`extra="forbid"` 尤其重要：模型爱"贴心地"多返回字段，这里直接拒绝，
避免下游拿到未经定义的隐含契约。

### 5. Invalid output 的处理：修复重试

```text
第 1 次输出坏 JSON
      ↓ parse/validate 失败 → StructuredOutputError(raw_text, reason, validation_errors)
把坏输出作为 assistant 消息回灌 + 追加 user 纠正指令
      ↓
第 2 次输出合法 JSON → Pydantic 通过（repairs=1）
```

两个设计要点：
- **宽容提取，严格校验**：`extract_json` 会剥掉 ```` ```json ```` 围栏和前后解释，
  但合法性仍交给 `json.loads` + `model_validate` 判断；
- **用量累加**：修复过程中所有尝试的 token 都要累加 —— 你确实为它们付了钱。

### 6. Streaming：改善的是首字延迟，不是总量

流式逐片 `yield` 增量文本；`transport.py` 的 SSE 解析处理
`data: {...}`、注释行、空行、坏 JSON 与 `data: [DONE]`。
实测 `MockProvider(chunk_size=10)` 把一段 JSON 切成 15 片。
注意：一旦开始产出 token 就不适合中途重试（会重复内容），这是后续话题。

### 7. 超时与重试：必须区分"能不能重试"

| 异常 | 触发 | 重试 |
|---|---|---|
| `LlmTimeoutError` | `asyncio.wait_for` 超时 | ✅ |
| `LlmConnectionError` | DNS/TLS/连接失败 | ✅ |
| `LlmRateLimitError` | HTTP 429 | ✅（优先用 `Retry-After`） |
| `LlmServerError` | HTTP 5xx | ✅（指数退避） |
| `LlmAuthError` | HTTP 401/403 | ❌ |
| `LlmClientError` | HTTP 400/404/422 | ❌ |

只看状态码不够，**必须知道"这个错能不能重试"**：对 401 做三次退避重试，
只会白等、白烧配额。退避公式 `base * 2^(attempt-1)` 且封顶 `max_delay_s`；
429 优先服从而不是覆盖服务端给的 `Retry-After`。

### 8. 费用与延迟：让约束可见

每次补全都返回 `usage`（prompt/completion/total）、`latency_ms`、`attempts`、`cost_usd`。
价格表可注入（示意值，真实项目以官方价目表为准）。
把成本放进返回值，是"成本护栏"的第一步。

### 9. 安全边界

- 构造真实传输**必须显式**给 `base_url`，没有隐式默认端点；
- **绝不读取** `os.environ`；不传 `api_key` 就不发送 `Authorization` 头；
- 异常消息不回显 key；`.gitignore` 默认忽略 `.env` 与 `*credentials*`；
- 全部测试/示例使用 mock 或 `httpx.MockTransport`：**不联网、不产生费用**。

### 10. 真实 API 与 mock 的差异

| 维度 | mock / scripted | 真实 API |
|---|---|---|
| 输出 | 确定性 | 非确定（temperature、模型漂移） |
| 失败 | 按脚本精确制造 | 随机、偶发、与负载相关 |
| 用量 | 近似估算 | 服务端精确返回 |
| 成本 | 0 | 按 token 计费（输出更贵） |
| reasoning | 忽略配置 | 影响延迟/成本/质量 |
| 安全 | 无凭据 | key 是最敏感资产 |

mock 的价值是**让失败路径可重复**；它不能替代对真实非确定性的观测。

## 命令一览

| 命令 | 演示内容 |
|---|---|
| `uv run llm-api-lab demo` | 结构化输出 happy path（raw 字符串 vs validated 对象） |
| `uv run llm-api-lab schema` | `TriageResult` 的 JSON Schema |
| `uv run llm-api-lab invalid-json` | 坏 JSON → 修复重试 → 通过 |
| `uv run llm-api-lab retry` | 429/503 退避重试（sleeper 记录，不真等待） |
| `uv run llm-api-lab stream` | 流式逐片输出与拼装 |
| `uv run llm-api-lab budget` | 上下文窗口超限，发送前拒绝 |

## 运行与验证

```bash
cd week3/llm-api-lab
uv sync
uv run pytest          # 74 passed
uv run llm-api-lab --help
```

### 实测证据（本机 macOS arm64 / uv 0.9.17 / Python 3.11.15 / pydantic 2.13.5 / httpx 0.28.1）

| 场景 | 命令 | 实测结果 |
|---|---|---|
| 全部测试 | `uv run pytest` | **74 passed in 0.18s**（成功 + 错误/边界） |
| 结构化 happy path | `llm-api-lab demo` | `repairs=0`；raw 是字符串，validated 是 `storage/warning/expand_or_clean_disk`；usage 501/38/539；latency 0.24 ms；cost $0 |
| 坏 JSON 修复 | `llm-api-lab invalid-json` | provider 调用 2 次，`repairs=1`，第二次通过校验 |
| 退避重试 | `llm-api-lab retry` | `attempts=3`，`delays=[0.2, 0.2]`（Retry-After + 指数退避） |
| 流式 | `llm-api-lab stream` | 多片 delta，`assembled` 为完整合法 JSON |
| 预算保护 | `llm-api-lab budget` | 发送前抛 `ContextWindowExceededError`：estimate 945 > available 48 |
| 重试/致命错误 | `examples/03_retry_and_errors.py` | 可重试 `attempts=3 delays=[0.3, 0.2]`；401 `attempts=1 (no retry)` |
| HTTP 传输 | `examples/04_http_transport.py` | 200：usage 42/11/53、cost $0.00001290；429 映射为 `LlmRateLimitError(retry_after_s=2.0)` |

测试分布（74 项）：

- `test_messages.py`（19）：角色、空消息拒绝、未知字段拒绝、system 顺序、token 估算、上下文窗口；
- `test_structured_output.py`（13）：JSON 提取（纯/围栏/夹叙）、坏 JSON、schema 不符、额外字段、修复成功/耗尽/禁用；
- `test_reliability.py`（11）：可重试后成功、重试耗尽、401/400 不重试、超时映射、注入时钟测延迟、默认/注入价格、退避封顶；
- `test_streaming.py`（6）：mock 流拼装、脚本分片、错误传播、SSE 解析（噪声/坏 JSON/`[DONE]`）；
- `test_transport_http.py`（16）：响应解析、usage 缺失兜底、reasoning 透传、请求体含 schema、鉴权头安全默认、状态码→异常树、429 Retry-After、缺 base_url、SSE 流、流式错误；
- `test_cli.py`（9）：六个命令的退出码与输出断言、未知命令退出 2。

## 验收对照（课程完成标准）

- [x] 理解普通文本输出与 Structured Output 的区别 —— 第 4 节 + `cli demo` 同时打印 raw/validated
- [x] 能用 Schema 约束输出 —— `response_format=json_schema` + 提示词内嵌 `model_json_schema()`
- [x] 能处理 invalid output —— `StructuredOutputError` + `complete_structured` 修复重试
- [x] 能实现 streaming —— `LLMClient.stream` / `collect_stream` + SSE 解析

## C# / .NET → Python 映射（增量）

| C# / .NET | 本周 Python |
|---|---|
| `HttpClient` + `Polly` 重试策略 | `httpx.AsyncClient` + `RetryPolicy` + 异常树 |
| `SemaphoreSlim` / `Task.WhenAll` | `asyncio.Semaphore` / `asyncio.gather`（Week 2 复用） |
| `CancellationTokenSource(timeout)` | `asyncio.wait_for(coro, timeout)` |
| `JsonSerializer.Deserialize<T>` | `json.loads` + `TriageResult.model_validate` |
| `IAsyncEnumerable<T>` | `async def` + `yield`（async generator） |
| `Func<T>` / `Action<T>` | 可注入的 `sleeper` / `clock`（测试确定性） |
| DTO + 校验特性 | `ResponseFormat.json_schema` + Pydantic `extra="forbid"` |

## 踩坑记录

| 现象 | 原因 | 解决 |
|---|---|---|
| 首次 `uv sync` 报 `OSError: Readme file does not exist: README.md` | hatchling 构建可编辑包时要求 `readme` 指向的文件存在（与 Week 1 同一个坑） | 先写 `README.md` 再 `uv sync` |
| `pytest` 的 `-v` 被 `addopts = "-q"` 抵消 | pytest 的 `q`/`v` 是累加的，净效果为默认 | 需要逐用例名时用 `-o addopts="" -v` |
| Pydantic `computed_field` 报 `prop-decorator` 类型告警 | `@computed_field` 叠在 `@property` 上，静态检查器不识别 | 加 `# type: ignore[prop-decorator]` |
| 不同厂商思维链字段名不一致 | 有的叫 `reasoning_content`，有的叫 `reasoning` | 解析时两种都尝试，取不到则 `None` |

## 与前后周的连接

- **接 Week 2**：`httpx.AsyncClient` 与 SSE 的心智模型直接复用；本周把 HTTP 细节
  收敛到 `Provider` 协议之后，业务层不再认识 httpx。
- **向 Week 4**：Tool Calling = "结构化输出 + 一个特殊的 `tool_calls` 字段 + 本地执行工具"。
  本周练熟的 `complete_structured`、异常树与重试策略会被直接复用。

## 练习 / 待办

1. `repair_attempts=0` 重跑 `invalid-json`，观察异常与 `raw_text`。
2. 给 `RetryPolicy` 加 `max_total_delay_s`，防止退避叠加成分钟级。
3. 设计"仅在首个 token 之前可重试"的流式调用，并写测试。
4. 对话超窗时从最旧的非 system 消息开始裁剪，直到放得下，并记录丢弃条数。
5. 接入 `tiktoken`，对比估算器与真实值的偏差。
6. 复用同一 `Provider` 协议再加一个厂商 Messages API provider。
7. 在 `LLMClient` 上累计会话成本，超阈值拒绝继续调用。
8. 加 `request_id` 与结构化日志（**不记录原文，可能含敏感信息**）。

## 本周记录

### 学到了什么
（待填：用自己的话复述 —— 模型只返回字符串；异常树驱动重试策略；Pydantic 是不可信输出的闸门）

### 遇到的问题
（待填：试运行中的报错与定位过程，可参考"踩坑记录"）

### 关键代码/Commit
（待填：`llm-api-lab`，本 handoff H001）

### 下周改进
（待填：接 Tool Calling 前想先补的能力）
