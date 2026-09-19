# Week 2 — Async + FastAPI（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 2 工作区，对应笔记：
`01-Projects/AI-Agent/24周学习计划/Week-02-Async-FastAPI`。

> 本目录由 Implementor（handoff H001）在**发现目录原本不存在**后创建。
> 目标目录 `~/ai-agent-24weeks/week2/` 在本次执行前不存在，因此本目录内容
> 均为新增，未覆盖任何既有用户文件。

---

## 本周覆盖情况（对照课程大纲）

| 大纲要求 | 本目录是否覆盖 | 载体 |
|---|---|---|
| async / await、asyncio | ✅ | `homelab-api/src/homelab_api/service_async.py`（`gather` + `Semaphore`） |
| HTTPX | ✅ | `examples/async_http_client.py`、`tests/test_async_client.py` |
| FastAPI | ✅ | `routers/` + `main.py`（`create_app`） |
| Depends | ✅ | `deps.py`（`SettingsDep` / `InventoryDep` / `ProbeDep`） |
| exception handler | ✅ | `errors.py`（领域异常 → 404/422/503/500 JSON 外壳） |
| REST API | ✅ | `/health`、`/hosts`、`/hosts/{name}`、`POST /hosts/check`、`/docker/status`、`/network/status` |
| SSE / WebSocket 基础 | ✅ | `events.py`（`GET /events/checks`、`WS /ws/checks`） |
| 实战：HomeLab API | ✅ | `homelab-api`（mock/内置清单，无需外部依赖） |
| 能说明 async 为何适合 Agent Tool | ✅ | `homelab-api/README.md` 第 6.1 节 + 笔记草稿 |
| 能写 async HTTP client | ✅ | `examples/async_http_client.py` |
| API 有测试和错误处理 | ✅ | `tests/`（成功 + 404/422/503 边界）+ `errors.py` |

### 尚未覆盖（留作练习，见 `homelab-api/README.md` 第 8 节）

- 真实异步 HTTP 探针（当前为 `asyncio.sleep` 模拟的确定性探针）
- 探针超时（`asyncio.wait_for`）→ 503 的完整链路
- 请求日志中间件 / `pydantic-settings` 环境变量配置
- 覆盖率报告（`pytest --cov`）

---

## 目录结构

```text
week2/
├── README.md                      # 本文件：Week 2 总览
├── homelab-api/                   # 可运行项目（见其 README）
│   ├── pyproject.toml             # fastapi / uvicorn / httpx + 复用 Week 1
│   ├── uv.lock
│   ├── .python-version
│   ├── README.md                  # 详细讲解 + 运行 + 练习
│   ├── examples/async_http_client.py
│   ├── src/homelab_api/
│   └── tests/
└── notes/
    └── Week-02-Async-FastAPI.md   # 交给 Knowledge 的笔记草稿副本
```

> Obsidian 笔记草稿的**权威副本**位于本 handoff 的
> `evidence/Week-02-Async-FastAPI.md`；`notes/` 下只是同内容的工作副本，
> 便于在项目内直接阅读。正式 vault 笔记由 Knowledge 阶段写入。

---

## 快速开始

```bash
cd homelab-api
uv sync                       # 安装 Python 3.11 + 依赖（含可编辑的 Week 1 项目）
uv run pytest                 # 全部测试通过
uv run homelab-api            # 启动服务，打开 http://127.0.0.1:8000/docs
uv run python examples/async_http_client.py   # 不启服务器跑异步客户端示例
```

---

## 一句话总结

Week 1 用 `Probe` 参数注入留好了替换点；Week 2 把 `service` 层搬到一个
**单线程事件循环 + `asyncio.Semaphore` 限流**的 FastAPI 服务后面，
用 `Depends` 做装配、用 `exception_handler` 统一错误契约、
用 `schemas` 隔离 API 边界 —— 领域层一行未改，却被完整复用。

下一周（Week 3）会在这个服务里接入 **LLM API**，把 `/hosts` 这类数据
交给模型做 tool calling。本周的 `httpx.AsyncClient` 与 `/docs` 自描述接口，
正是为调用外部 LLM API 做的准备。
