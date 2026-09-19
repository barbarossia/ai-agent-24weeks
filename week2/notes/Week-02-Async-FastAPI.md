---
title: Week-02-Async-FastAPI
type: learning-note
project: AI-Agent
week: 2
status: draft
created: 2026-09-19
tags:
  - AI-Agent
  - Python
  - Async
  - FastAPI
  - learning-plan
source_task: PYTHON-week2-async-fastapi-learning
---

# Week 02 — Async + FastAPI

> 上一周：[[Week-01-Python-Backend基础]] | 下一周：[[Week-03-LLM-API基础]]

> [!abstract] 本周一句话
> 把 Week 1 的同步领域层**一行未改**地搬到一个"单线程事件循环 + 信号量限流"的
> FastAPI 服务后面：用 `Depends` 装配、用 `exception_handler` 统一错误契约、
> 用 `schemas` 隔离 API 边界 —— 从而理解 Agent Tool 为什么天然需要异步。

## 目标

掌握 Agent Tool 常用的异步 I/O 与 API 服务能力，并回答一个核心问题：
**为什么 async 适合 Agent Tool？**

Agent 的工作负载几乎全是 I/O 等待（调 LLM API、查向量库、访问 MCP Server、探测主机）。
同步模型下线程在等待 I/O 时只能阻塞；asyncio 在单线程事件循环内用协程切换，
等待期间去推进别的任务。于是一个进程能用很小的内存同时推进成百上千个工具调用。

## 学习内容

- async / await、asyncio（`gather`、`Semaphore`、事件循环心智模型）
- HTTPX（`AsyncClient` + `ASGITransport`）
- FastAPI、`Depends`、exception handler
- REST API 设计（状态码语义、统一错误外壳）
- Pydantic 请求/响应模型与领域模型的边界
- SSE / WebSocket 基础

## 实战产出

项目：**`homelab-api`** —— 把 Week 1 的 HomeLab 主机检查包装成 REST API。

```text
                    ┌──────────────── homelab-api (Week 2) ────────────────┐
HTTP 请求 ──▶ routers ──▶ deps (Depends) ──▶ service_async ──▶ ai_agent_lab │
   ▲             │             │                   │        (Week 1 领域层) │
   │             ▼             ▼                   ▼                       │
JSON 响应 ◀── schemas ◀── 错误处理器 ◀── asyncio.gather + Semaphore ───────┘
```

工作区 `~/ai-agent-24weeks/week2/homelab-api/`：

```text
homelab-api/
├── pyproject.toml            # fastapi / uvicorn / httpx + 对 Week 1 的可编辑路径依赖
├── uv.lock                   # 锁定 31 个包
├── .python-version           # Python 3.11
├── README.md                 # 详细讲解 + 运行 + 练习
├── examples/async_http_client.py
├── src/homelab_api/
│   ├── schemas.py            # API 边界模型（请求/响应/错误）
│   ├── service_async.py      # 异步业务层：探针、并发、信号量
│   ├── deps.py               # Depends 提供者 + 类型别名
│   ├── errors.py             # 领域异常 → HTTP + JSON 外壳
│   ├── events.py             # SSE + WebSocket
│   ├── main.py               # create_app() 应用工厂
│   └── routers/{health,hosts,status}.py
└── tests/                    # 26 个用例
```

### 复用 Week 1 的方式

```toml
dependencies = ["fastapi", "uvicorn[standard]", "httpx", "ai-agent-lab"]

[tool.uv.sources]
ai-agent-lab = { path = "../../week1/ai-agent-lab", editable = true }
```

`editable = true` 让 Week 2 的 `.venv` 直指 Week 1 源码目录：改 Week 1 立即生效，
不需发版或复制粘贴。C# 对照：≈ `<ProjectReference>`，而不是引 NuGet 包。
**Week 1 的 `models / service / errors` 一行未改即被完整复用。**

## 接口一览

| 方法 | 路径 | 说明 | 成功 | 错误 |
|---|---|---|---|---|
| GET | `/health` | 存活探针 | 200 | — |
| GET | `/hosts` | 列出全部主机 | 200 | — |
| GET | `/hosts/{name}` | 查单台主机 | 200 | 404 |
| POST | `/hosts/check` | 批量并发检查（请求体） | 200 | 404 / 422 |
| GET | `/docker/status` | docker 主机状态 | 200 | 503 |
| GET | `/network/status` | 网络设备状态 | 200 | 503 |
| GET | `/events/checks` | SSE 逐条推送检查结果 | 200 | — |
| WS | `/ws/checks` | WebSocket 按名检查 | — | 错误 JSON |
| GET | `/docs` | 自动交互文档 | 200 | — |

> `/docker/status`、`/network/status` 是计划硬性要求；
> `POST /hosts/check`、`/events/checks`、`/ws/checks` 是为覆盖
> "Pydantic 请求模型 / SSE / WebSocket"三个学习目标而加的最小补充。

## 关键代码与概念

### 1. 并发 + 限流（`service_async.py`）

```python
async def check_all_async(hosts, probe, concurrency=4, meter=None):
    if concurrency < 1:
        raise ValueError(...)                  # 防止 Semaphore(0) 永久挂起
    semaphore = asyncio.Semaphore(concurrency)
    async def run_one(host):
        async with semaphore:                  # 同时在飞的探针 ≤ concurrency
            return await check_host_async(host, probe=probe)
    return list(await asyncio.gather(*(run_one(h) for h in hosts)))
```

- `asyncio.gather` **保持输入顺序**返回结果，无需手动排序。
- 信号量限制并发，避免一次性打开过多连接打垮下游。
- `ConcurrencyMeter` 统计"同时执行的峰值"，让并发测试**确定性**通过，
  不依赖脆弱的墙钟时间断言。

**头号陷阱：不要在 async 函数里写阻塞调用。** `time.sleep` / `requests` / 同步文件 IO
会卡住整个事件循环。要么用异步版本，要么用 `asyncio.to_thread(...)`。

### 2. 依赖注入（`deps.py`）

```python
SettingsDep  = Annotated[AppSettings, Depends(get_settings)]
InventoryDep = Annotated[Inventory,   Depends(get_inventory)]
ProbeDep     = Annotated[AsyncProbe,  Depends(get_probe)]
```

价值：复用、可测（`app.dependency_overrides[get_probe] = lambda: fake`）、显式。
这是 Week 1 "把 probe 当参数注入"思想的框架化版本。

### 3. 统一错误契约（`errors.py`）

| 领域异常 | HTTP | `error.code` |
|---|---|---|
| `HostNotFoundError` | 404 | `host_not_found` |
| `InventoryError` | 422 | `inventory_error` |
| `CheckFailedError` | 503 | `check_failed` |
| `RequestValidationError` | 422 | `validation_error` |
| 其他 `AiAgentLabError` | 500 | `internal_error` |

响应外壳统一为 `{"error": {"code", "message", "hostname"}}`；
客户端只读 `error.code` 做分支，不解析人类文案。
Week 1 是"异常树 + 退出码"，Week 2 换成"异常树 + HTTP 状态码 + JSON 外壳"，分层不变。

### 4. 领域模型 ≠ API 契约（`schemas.py`）

即使 `ai_agent_lab.models.Host` 已是 Pydantic 模型，API 仍单独定义
`HostOut / CheckResultOut / SummaryOut`：领域模型随重构而变，API 契约要对客户端稳定；
且只暴露允许公开的字段。对照 C#：Entity 与 DTO/ViewModel 分离。

### 5. SSE 与 WebSocket（`events.py`）

- **SSE**：服务器→客户端单向流，基于普通 HTTP，用异步生成器逐条 `yield`。
  LLM 逐 token 输出就是典型用例。
- **WebSocket**：双向长连接，适合需要客户端持续发指令的交互式会话。

## 运行与验证

```bash
cd week2/homelab-api
uv sync                                         # 安装 Python 3.11 + 依赖
uv run pytest -q                                # 26 passed
uv run homelab-api                              # http://127.0.0.1:8000/docs
uv run python examples/async_http_client.py     # 免服务器异步客户端示例
```

### 实测证据（本机 Python 3.11.15 / fastapi 0.141.1 / httpx 0.28.1）

| 场景 | 命令 | 实测结果 |
|---|---|---|
| 存活探针 | `curl /health` | `200` `{"status":"ok","service":"homelab-api","version":"0.1.0","week":2}` |
| 列表 | `curl /hosts` | `200`，4 台主机 |
| 单台成功 | `curl /hosts/openwrt-01` | `200`，kind=`openwrt` |
| 单台 404 | `curl /hosts/ghost-01` | `404`，`error.code=host_not_found` |
| 批量成功 | `POST /hosts/check` | `200`，3 台全 `up`，`summary.healthy=true` |
| 请求校验 422 | `POST /hosts/check {"names":[]}` | `422`，`error.code=validation_error` |
| docker 状态 | `curl /docker/status` | `200`，1 台 docker `up` |
| network 状态 | `curl /network/status` | `200`，openwrt-01 `up` |
| SSE | `curl /events/checks` | 逐条 `event: check` … `event: done` |
| WebSocket | `ws /ws/checks` | 发送 `openwrt-01` → `up`；`ghost-01` → `host_not_found` |
| 自动文档 | `curl /docs` | `200` |
| 测试 | `uv run pytest -q` | **26 passed**（成功 + 404/422/503 边界） |

## 验收对照

- [x] 能解释 async 为什么适合 Agent Tool —— 见"目标"与"关键代码 1"
- [x] 能写 async HTTP client —— `examples/async_http_client.py`、`tests/test_async_client.py`
- [x] 能建立 FastAPI 服务 —— `create_app()` + 三组 router + SSE/WS
- [x] API 有测试和错误处理 —— 26 用例 + `errors.py` 统一错误契约

## 踩坑记录

| 现象 | 原因 | 解决 |
|---|---|---|
| `Distribution not found ... week1/ai-agent-lab` | 路径依赖相对层级算错（`../` 应是 `../../`） | 从 `homelab-api/` 出发修正为 `../../week1/ai-agent-lab` |
| `attempted relative import beyond top-level package` | `events.py` 在顶层包内却写了 `from ..deps` | 顶层模块用 `from .deps`；仅 `routers/` 子包才用 `from ..deps` |
| `Semaphore(0)` 会让 `gather` 永久挂起 | 未校验 `concurrency` | 显式 `raise ValueError`，并补边界测试 |
| FastAPI 0.141 `app.routes` 看不到子路由 | Starlette 1.6 改为 `_IncludedRouter` 嵌套表示 | 非 bug：以 `/openapi.json` 或实际请求验证路由 |

## 与前后周的连接

- **接 Week 1**：`Probe` 注入点被替换成 `AsyncProbe`；`service` 层被 FastAPI 复用。
- **向 Week 3**：`httpx.AsyncClient` 与 `/docs` 自描述接口，正是调用外部 LLM API
  与做 tool calling 的准备。

## 练习 / 待办

1. `GET /hosts/{name}/check`（复用 `check_host_async` + 补测试）。
2. 探针超时：`asyncio.wait_for` → `CheckFailedError` → 503。
3. 真实异步 HTTP 探针（`httpx.AsyncClient` 探测另一个本地端口）。
4. `GET /status/overview`：对比顺序执行与 `gather` 的耗时。
5. 给 SSE 加 `?kind=` 过滤。
6. 请求日志中间件（注意不要记录敏感信息）。
7. `pydantic-settings` 把配置改为环境变量注入。

## 本周记录

### 学到了什么
（待填：用自己的话复述事件循环 / 信号量 / Depends 三点）

### 遇到的问题
（待填：试运行中遇到的报错与定位过程）

### 关键代码/Commit
（待填：`homelab-api`，本 handoff H001）

### 下周改进
（待填：接入 LLM API 前想先补的能力）
