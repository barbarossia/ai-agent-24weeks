# homelab-api — Week 2（Async + FastAPI）

> 24 周 AI Agent Engineer 学习计划的第二个可运行项目。
> 主题：**async / await、asyncio、HTTPX、FastAPI、Depends、exception handler、REST、SSE / WebSocket**。
>
> 目标不是"会写路由"，而是理解 **为什么 Agent Tool 天然需要异步**，
> 并把 Week 1 的同步领域层**原样复用**到一个可测试的异步 HTTP 服务后面。

---

## 1. 它是什么

把 Week 1 的 **HomeLab 主机检查**（`ai_agent_lab`）包装成一个 REST API：

```
                    ┌──────────────── homelab-api (Week 2) ────────────────┐
HTTP 请求 ──▶ routers ──▶ deps (Depends) ──▶ service_async ──▶ ai_agent_lab │
   ▲             │             │                   │        (Week 1 领域层) │
   │             ▼             ▼                   ▼                       │
JSON 响应 ◀── schemas ◀── 错误处理器 ◀── asyncio.gather + Semaphore ───────┘
```

**关键点：Week 1 的 `models / service / errors` 一行未改就被复用**（通过
`pyproject.toml` 里的可编辑路径依赖）。这正是 Week 1 README 预告的分层回报。

---

## 2. 环境准备（继续用 uv）

```bash
cd week2/homelab-api

uv python install      # 按 .python-version 安装 Python 3.11
uv sync                # 解析依赖、创建 .venv、安装 Week 1 项目（editable）
uv tree                # 查看依赖树
```

`pyproject.toml` 里最关键的两行：

```toml
dependencies = ["fastapi", "uvicorn[standard]", "httpx", "ai-agent-lab"]

[tool.uv.sources]
ai-agent-lab = { path = "../../week1/ai-agent-lab", editable = true }
```

> `editable = true` 意味着本项目的 `.venv` 直指 Week 1 源码目录：
> 改 Week 1 的 `service.py`，这里**立即生效**，不需要发版或复制粘贴。
> C# 对照：≈ 项目引用（`<ProjectReference>`），而不是引 NuGet 包。

---

## 3. 运行方式

### 3.1 启动服务

```bash
uv run homelab-api                 # 或：uv run python -m homelab_api
# 监听 http://127.0.0.1:8000（默认仅本机）

uv run homelab-api --reload        # 开发模式：改代码自动重启
uv run homelab-api --port 9000     # 换端口
```

启动后打开 **http://127.0.0.1:8000/docs** —— FastAPI 会自动生成交互式 OpenAPI 文档，
可以直接在浏览器里点 "Try it out" 调每个接口。这是本周最直观的学习工具。

### 3.2 用 curl 验证（另开一个终端）

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","service":"homelab-api","version":"0.1.0","week":2}

curl -s http://127.0.0.1:8000/hosts
# [{"name":"esxi-01","kind":"esxi",...}, ...]

curl -s http://127.0.0.1:8000/docker/status
curl -s http://127.0.0.1:8000/network/status

# 成功请求：批量并发检查
curl -s -X POST http://127.0.0.1:8000/hosts/check \
  -H 'content-type: application/json' \
  -d '{"names":["esxi-01","docker-01"],"concurrency":2}'

# 错误路径：未知主机 → 404
curl -s -i http://127.0.0.1:8000/hosts/ghost-01

# 错误路径：请求体非法 → 422
curl -s -i -X POST http://127.0.0.1:8000/hosts/check \
  -H 'content-type: application/json' -d '{"names":[]}'
```

### 3.3 不启动服务器也能跑异步客户端示例

```bash
uv run python examples/async_http_client.py
```

该脚本用 `httpx.ASGITransport` 把请求**直接送进进程内的 app**，
不占端口、不访问外网，演示 `asyncio.gather` 并发发多个请求。

---

## 4. 接口一览

| 方法 | 路径 | 说明 | 成功 | 错误 |
|---|---|---|---|---|
| GET | `/health` | 存活探针 | 200 | — |
| GET | `/hosts` | 列出全部主机 | 200 | — |
| GET | `/hosts/{name}` | 查单台主机 | 200 | 404 |
| POST | `/hosts/check` | 批量并发检查（请求体） | 200 | 404 / 422 |
| GET | `/docker/status` | docker 主机状态 | 200 | 503 |
| GET | `/network/status` | 网络设备状态 | 200 | 503 |
| GET | `/events/checks` | **SSE** 逐条推送检查结果 | 200 | — |
| WS | `/ws/checks` | **WebSocket** 按名检查 | — | 错误 JSON |
| GET | `/docs` | 自动交互文档 | 200 | — |

> 题外话：计划里 `GET /docker/status`、`GET /network/status` 是硬性要求；
> `POST /hosts/check` 与 `/events/checks`、`/ws/checks` 是为了覆盖
> "Pydantic 请求模型 / SSE / WebSocket" 这三个学习目标而加的**最小补充**。

### 统一错误契约

所有错误都返回同一种外壳，客户端只读 `error.code` 做分支，不解析人类文案：

```json
{ "error": { "code": "host_not_found", "message": "host not found: 'ghost-01'", "hostname": "ghost-01" } }
```

| 领域异常 | HTTP | `error.code` |
|---|---|---|
| `HostNotFoundError` | 404 | `host_not_found` |
| `InventoryError` | 422 | `inventory_error` |
| `CheckFailedError` | 503 | `check_failed` |
| `RequestValidationError` | 422 | `validation_error` |
| 其他 `AiAgentLabError` | 500 | `internal_error` |

---

## 5. 代码结构

```text
homelab-api/
├── pyproject.toml            # 依赖 + 可编辑路径依赖 + pytest 配置
├── uv.lock                   # 锁定全部版本 → 可复现
├── .python-version           # Python 3.11
├── README.md                 # 本文件
├── examples/
│   └── async_http_client.py  # httpx.AsyncClient + ASGITransport 示例
├── src/homelab_api/
│   ├── __init__.py           # 版本号
│   ├── __main__.py           # python -m homelab_api → uvicorn
│   ├── py.typed              # 声明本包带类型信息
│   ├── schemas.py            # API 边界模型（请求/响应/错误）
│   ├── service_async.py      # 异步业务层：探针、并发、信号量
│   ├── deps.py               # Depends 依赖提供者 + 类型别名
│   ├── errors.py             # 领域异常 → HTTP 状态码 + JSON 外壳
│   ├── main.py               # create_app() 应用工厂
│   └── routers/
│       ├── health.py         # GET /health
│       ├── hosts.py          # /hosts 系列
│       └── status.py         # /docker/status、/network/status
│   └── events.py             # SSE + WebSocket
└── tests/
    ├── conftest.py           # app / client fixtures + 快速探针
    ├── test_async.py         # 异步模型 + 并发边界
    ├── test_health.py
    ├── test_hosts.py         # 成功 + 404 + 422
    ├── test_status.py        # 成功 + 空结果边界 + 503
    ├── test_events.py        # SSE + WebSocket
    └── test_async_client.py  # 异步 HTTP 客户端
```

分层：`routers → deps → service_async → ai_agent_lab(领域层)`。
`service_async` 不认识 HTTP，`routers` 不写业务规则 —— 与 Week 1 的
`cli → service → models` 是同一条纪律。

---

## 6. 逐模块讲解

### 6.1 `service_async.py` —— 为什么 async 适合 Agent Tool

Agent 的工作负载几乎全是 **I/O 等待**：调 LLM API、查向量库、访问 MCP Server、探测主机。
同步模型下，一个线程等待 I/O 时只能阻塞；asyncio 在**单线程事件循环**内用协程切换，
等待期间去推进别的任务。于是一个进程能用很小的内存同时推进成百上千个工具调用。

| 概念 | Python | C# / .NET 对照 |
|---|---|---|
| 协程函数 | `async def f() -> T` | `async Task<T> f()` |
| 等待结果 | `await f()` | `await f()` |
| 并发等待 | `asyncio.gather(a, b)` | `Task.WhenAll(a, b)` |
| 并发上限 | `asyncio.Semaphore(n)` | `SemaphoreSlim(n)` |
| 让出事件循环 | `await asyncio.sleep(s)` | `await Task.Delay(ms)` |

**头号陷阱：不要在 async 函数里写阻塞调用。**
`time.sleep(1)`、`requests.get(...)`、同步文件 IO 会卡住整个事件循环，
让所有并发连接一起变慢。要么用异步版本（`asyncio.sleep` / `httpx.AsyncClient`），
要么用 `asyncio.to_thread(...)` 把阻塞活丢到线程池。

本模块的关键实现：

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
- 信号量限制并发，避免一次性打开过多连接把下游打垮。
- `ConcurrencyMeter` 记录"同时执行的峰值"，让并发测试**确定性**通过，
  不依赖脆弱的墙钟时间断言。

### 6.2 `deps.py` —— `Depends` 依赖注入

路由只**声明**需要什么，框架负责构造：

```python
SettingsDep  = Annotated[AppSettings, Depends(get_settings)]
InventoryDep = Annotated[Inventory,   Depends(get_inventory)]
ProbeDep     = Annotated[AsyncProbe,  Depends(get_probe)]
```

价值：
- **复用**：清单/探针/配置只写一次，多个路由共享；
- **可测**：`app.dependency_overrides[get_probe] = lambda: fake` 即可注入假实现，
  不读文件、不发网络、不等待；
- **显式**：依赖关系写在函数签名里，不像全局单例那样隐蔽。

这正是 Week 1 "把 `probe` 当参数注入" 的思想，被框架升级为"函数参数级容器"。

### 6.3 `schemas.py` —— 领域模型 ≠ API 契约

即使 `ai_agent_lab.models.Host` 已经是个 Pydantic 模型，API 仍单独定义
`HostOut / CheckResultOut / SummaryOut`。原因：
- **稳定**：领域模型会随内部重构而变，API 契约要对客户端稳定；
- **安全**：只暴露允许公开的字段，不泄露内部结构；
- **职责**：`CheckRequest` 是请求校验（`min_length=1`、`ge/le`、`extra="forbid"`），
  校验失败自动 422。

对照 C#：Entity 与 DTO/ViewModel 的分离。

### 6.4 `errors.py` —— 异常树 + HTTP 状态码

Week 1 的目标是"异常树 + 退出码"；Week 2 把最外层消费者从 shell 换成 HTTP 客户端，
于是变成"异常树 + HTTP 状态码 + JSON 外壳"。处理器与路由解耦：
任何一个 handler 抛领域异常，都会自动得到一致的状态码与 JSON 结构，不用到处 `try/except`。

### 6.5 `events.py` —— SSE 与 WebSocket

- **SSE**（`GET /events/checks`）：服务器 → 客户端单向流，基于普通 HTTP。
  LLM 逐 token 输出、工具执行进度就是典型用例；
  它用异步生成器逐个 `yield`，每台主机一就绪就推给客户端。
- **WebSocket**（`/ws/checks`）：双向长连接，适合需要客户端持续发指令的交互式会话。

两者都依赖"单线程事件循环能同时挂起很多连接"这一 async 特性。

---

## 7. 测试

```bash
uv run pytest              # 全部
uv run pytest -v           # 详细
uv run pytest tests/test_async.py -v
uv run pytest -k "503" -v
```

测试覆盖（成功 + 错误/边界都有）：

- **异步模型**：探针确定性、异常包装、`gather` 并发且被信号量限制、空列表、非法并发值。
- **health**：`/health` 字段契约、根路径。
- **hosts**：列表/单台成功、未知主机 404、批量检查成功、空 `names` 422、
  `concurrency` 越界 422、多余字段 422。
- **status**：docker/network 成功、空分类 healthy 边界、探针失败 503。
- **events**：SSE 事件流、WebSocket 成功、WebSocket 未知主机错误 JSON。
- **async client**：`httpx.AsyncClient` + `ASGITransport` 并发请求。

> 测试用 `app.dependency_overrides` 注入**零等待探针**，所以既快又确定，
> 不依赖真实网络。这是"可测试设计"的直接红利。

---

## 8. 练习方向（从模仿到独立）

1. **加 `GET /hosts/{name}/check`**：复用 `check_host_async`，补成功 + 404 测试。
2. **给探针加超时**：`asyncio.wait_for(probe(host), timeout=...)`，
   超时映射为 `CheckFailedError` → 503，并补测试。
3. **写一个真的异步 HTTP 探针**：用 `httpx.AsyncClient` 去 `GET` 主机的
   `/health`（例如指向另一个本地端口），并用 `dependency_overrides` 在测试里替换。
   这是"能写 async HTTP client"的进一步练习。
4. **实现 `GET /status/overview`**：一次返回 docker + network + 全部主机汇总，
   对比顺序执行与 `asyncio.gather` 的耗时差（用 `time.perf_counter` 观察）。
5. **给 SSE 加过滤参数**：`?kind=docker`，只推某类主机。
6. **加请求日志中间件**：记录方法、路径、耗时、状态码（注意不要记录请求体里的敏感信息）。
7. **接入 `pydantic-settings`**：把 `AppSettings` 改为从环境变量读取，
   体会配置注入而不是硬编码。

---

## 9. 常见错误与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: homelab_api` | 没装项目 / 没进环境 | `uv sync`，并用 `uv run ...` |
| `Readme file does not exist: README.md` | `pyproject.toml` 声明了 readme 但文件缺失 | 补 `README.md` |
| `Distribution not found ... ai-agent-lab` | 路径依赖写错 | 从 `homelab-api/` 看应为 `../../week1/ai-agent-lab` |
| `Address already in use` | 8000 端口被占 | `--port 8001` 或结束占用进程 |
| 接口返回 422 | 请求体不满足 `CheckRequest` 约束 | 看 `error.message` 里的字段路径 |
| 接口返回 503 | 探针抛异常（`check_failed`） | 检查下游是否可用；这是"暂时性故障"语义 |
| 并发没变快 | async 函数里有阻塞调用 | 换异步库，或用 `asyncio.to_thread` |
| 改了 Week 1 代码但没生效 | `editable` 依赖指向源码目录 | 确认 `uv sync` 已装、看 `.venv` 里的路径 |

---

## 10. C# / .NET → Python 速查（Week 2 增量）

| C# / .NET | Python（本项目） |
|---|---|
| `async Task<T>` | `async def -> T` |
| `await task` | `await coro` |
| `Task.WhenAll` | `asyncio.gather` |
| `SemaphoreSlim` | `asyncio.Semaphore` |
| `Task.Delay(ms)` | `asyncio.sleep(s)` |
| ASP.NET Core Controller | FastAPI `APIRouter` + 装饰器 |
| `[FromBody] Dto` | 函数参数类型为 Pydantic `BaseModel` |
| 依赖注入容器 | `Depends` / `app.dependency_overrides` |
| `IExceptionHandler` / 中间件 | `@app.exception_handler` |
| SignalR | WebSocket / SSE |
| Swagger / NSwag | 内置 `/docs`、`/openapi.json` |
