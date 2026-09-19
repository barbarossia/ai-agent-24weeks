---
title: Week-01-Python-Backend基础
type: learning-note
project: AI-Agent
week: 1
status: draft-for-knowledge
created: 2026-09-19
tags:
  - AI-Agent
  - Python
  - Backend
  - learning-plan
source_task: PYTHON-backend-week1-learning
---

# Week 01 — Python Backend 基础

> 总路线：[[../AI-Agent-Engineer-24周学习计划]] | 下一周：[[Week-02-Async-FastAPI]]

> [!abstract] 本周一句话
> 把"看过语法"变成"写得出来"：用 Pydantic 守数据边界、dataclass 表达内部值对象、
> 异常树统一错误语义、uv 锁定环境、pytest 保护行为，最终交付一个 typed CLI。

## 目标

从 C#/.NET 工程师视角掌握**现代 Python 工程基础**，落地为一个可运行、
可测试、可复用的小项目，为 Week 2 的 async / FastAPI 打地基。

## 学习内容

- typing 与 type hints（运行时是否校验）
- dataclass 与 Pydantic 的取舍
- exception handling（异常树、异常链、错误→退出码）
- virtual environment 与包管理（uv）
- pytest 基础（fixture、parametrize、monkeypatch、capsys）
- C# → Python 映射：DTO → Pydantic Model，Task\<T\> → async def

## 实战产出

项目：**`ai-agent-lab`** —— HomeLab 主机状态检查 CLI。

```text
inventory.json ──▶ Pydantic 校验 ──▶ Host ──▶ Probe 探针 ──▶ CheckResult
                                                                │
                                                     ┌──────────┴──────────┐
                                                     ▼                     ▼
                                                文本表格                JSON 输出
```

目录（Week 1 工作区 `~/ai-agent-24weeks/week1/`）：

```text
ai-agent-lab/
├── pyproject.toml          # 依赖 + 入口点 + pytest 配置
├── uv.lock                 # 依赖锁定 → 可复现
├── .python-version         # 锁定 Python 3.11
├── README.md               # 详细讲解 + 运行 + 练习
├── examples/inventory.json
├── src/ai_agent_lab/
│   ├── __init__.py
│   ├── __main__.py         # python -m ai_agent_lab
│   ├── py.typed
│   ├── errors.py           # 异常层级
│   ├── models.py           # Pydantic + dataclass + StrEnum
│   ├── service.py          # 业务逻辑（不依赖 CLI）
│   └── cli.py              # argparse + 渲染 + 退出码
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_service.py
    └── test_cli.py
```

分层：`cli → service → models`。service 不认识命令行，未来可被 FastAPI / MCP Server 复用。

---

## 核心概念

### 1. type hints 默认只是"文档"，不校验

```python
def f(x: int) -> int:
    return x

f("hello")   # 运行时不会报错！type hints 只对 mypy/pyright 有意义
```

要**运行时**校验，必须借助 Pydantic 这类库：它读取类型注解并生成校验器。
本周第一个认知转折点：**注解 ≠ 校验**。

### 2. Pydantic 守边界，dataclass 做内部值对象

- **Pydantic**：数据来自用户 / 文件 / 网络 / **LLM 输出**时使用。要校验、要转换。
- **dataclass**：数据只在代码内部流转、形状已知时使用。更轻、更快、无依赖。

```python
class Host(BaseModel):                       # 边界
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Hostname
    kind: HostKind
    address: str
    tags: list[str] = Field(default_factory=list)
    expected_latency_ms: int = Field(default=100, ge=1, le=10_000)

@dataclass(frozen=True, slots=True)
class CheckSummary:                          # 内部
    total: int
    up: int
    degraded: int
    down: int
    unknown: int
```

关键配置：

- `frozen=True`：实例不可变（对应 C# `record` / `readonly`）。
- `extra="forbid"`：拒绝未知字段 —— 拼错的配置不会被静默忽略。
- `Annotated[str, Field(pattern=...)]`：受限字符串类型（主机名），一处定义多处复用。
- `field_validator`：字段级归一化（tags 去空格 / 去重 / 排序）。
- `model_validator(mode="after")`：跨字段校验（主机名唯一）。

> [!warning] 为什么这点对 Agent 特别重要
> Week 3 会让 LLM 输出 JSON，再用 Pydantic 校验成强类型对象。
> **Pydantic 就是"LLM 不可信输出"和"程序可信数据"之间的那道闸门。**
> 本周提前把这道闸门练熟。

### 3. 异常：一棵可分类捕获的树

```python
class AiAgentLabError(Exception): ...
class InventoryError(AiAgentLabError): ...        # 清单非法
class HostNotFoundError(AiAgentLabError): ...     # 主机不存在
class CheckFailedError(AiAgentLabError): ...      # 检查执行失败
```

- 建树后，调用方可以精确捕获，也可以基类兜底。
- `raise X from exc` 保留异常链（C# 的 InnerException）。
- 异常携带结构化字段（`exc.hostname`），上层无需解析错误字符串。

`load_inventory` 把**三层错误**统一包装：

1. 文件不存在 / 读不了 → `InventoryError`
2. JSON 语法错误 → `InventoryError`（带行列号）
3. schema 校验失败 → `InventoryError`（带错误数量）

调用方只需处理一种领域异常。

### 4. 依赖注入：`Probe` 让业务可测试

```python
Probe = Callable[[Host], int]          # 类比 C# 的 Func<Host, int>

def check_host(host: Host, probe: Probe = default_probe) -> CheckResult: ...
```

- `default_probe` 用 `hashlib` 从主机名派生**确定性**延迟：不访问网络，测试不 flaky。
- 测试里传入固定探针即可完全掌控结果：`check_host(host, probe=lambda h: 250)`。
- 这个注入点也是 Week 2 把它换成**异步 HTTP 客户端**的接口预留。

### 5. 包管理：uv（本项目实际采用）

| 文件 | 作用 | C# 对照 |
|---|---|---|
| `pyproject.toml` | 项目元数据 + 依赖声明 | `.csproj` |
| `uv.lock` | 精确锁定依赖版本 | `packages.lock.json` |
| `.python-version` | 锁定 Python 版本 | `global.json`（SDK 版本） |
| `.venv/` | uv 管理的虚拟环境 | `obj/` + 还原产物 |
| `uv sync` | 按锁文件同步环境 | `dotnet restore` |
| `uv run <cmd>` | 在项目环境内执行 | `dotnet run` |

常用命令：

```bash
uv python install      # 按 .python-version 准备解释器
uv sync                # 创建 .venv 并安装依赖
uv add <pkg>           # 添加运行时依赖并更新 lock
uv add --dev <pkg>     # 添加开发依赖
uv run pytest          # 在项目环境内运行
```

### 6. pytest：fixture / parametrize / monkeypatch / capsys

- `@pytest.fixture`：共享测试数据（`conftest.py` 中的 `esxi_host`、`inventory`）。
- `@pytest.mark.parametrize`：一个测试跑多组边界值（`classify` 的 5 个边界）。
- `monkeypatch`：替换依赖，制造"一定 DOWN"等难以自然出现的场景。
- `capsys`：捕获 stdout/stderr，断言 CLI 输出。
- 直接调用 `main(["check-all"])` 返回退出码，**不必启动子进程**，测试又快又稳。

---

## 关键代码

### classify —— 边界清晰的状态判定

```python
def classify(host: Host, latency_ms: int) -> HealthStatus:
    if latency_ms <= host.expected_latency_ms:          # 边界：等于 → UP
        return HealthStatus.UP
    if latency_ms <= host.expected_latency_ms * 2:      # 边界：2x → DEGRADED
        return HealthStatus.DEGRADED
    return HealthStatus.DOWN
```

### 错误 → 退出码映射（CLI 只做 I/O）

```python
except HostNotFoundError as exc:   return 2   # 输入/数据错误
except InventoryError as exc:      return 2
except CheckFailedError as exc:    return 3   # 执行失败
# 检查完成但有 DOWN → return 1（可直接用于 CI）
```

这类"领域异常 → 进程退出码"的映射，是 CLI 工具可脚本化、可被 CI 消费的关键。

---

## 验证结果

环境：macOS (arm64)，uv 0.9.17，Python 3.11.15（uv 管理），pydantic 2.13.5，pytest 9.1.1。

```bash
$ uv sync
Installed 11 packages

$ uv run pytest
35 passed in 0.04s

$ uv run ai-agent-lab check-all
HOST          KIND      STATUS        LATENCY  MESSAGE
------------------------------------------------------
esxi-01       esxi      UP              114ms  ok
docker-01     docker    UP               76ms  ok
openwrt-01    openwrt   UP               10ms  ok
nas-01        host      UP               49ms  ok

summary: 4 up, 0 degraded, 0 down, 0 unknown => HEALTHY
[exit=0]

$ uv run ai-agent-lab check ghost-99
error: 'ghost-99' not found in inventory
[exit=2]

$ uv run ai-agent-lab --inventory /tmp/bad.json list
error: inventory is not valid JSON: /tmp/bad.json (line 1, column 1)
[exit=2]
```

测试覆盖（35 项）：

- **模型**：合法/非法主机名、tags 归一化、未知字段拒绝、不可变性、重名检测、汇总健康规则。
- **业务**：`classify` 5 个边界、探针注入、异常包装（保留 `__cause__`）、
  清单三层错误、空汇总。
- **CLI**：`list` / `check` / `check-all`、JSON 可解析、未知主机 → 2、
  非法清单 → 2、存在 DOWN → 1、缺少子命令 → argparse 退出。

---

## C# / .NET → Python 映射

| C# / .NET | Python（本周项目） |
|---|---|
| `record` / DTO | `@dataclass` / Pydantic `BaseModel` |
| `DataAnnotations` / FluentValidation | Pydantic `Field` / validators |
| `Nullable<T>` | `T \| None` |
| `Task<T>` | `async def -> T`（Week 2） |
| `Func<Host,int>` | `Callable[[Host], int]` |
| `enum` | `enum.StrEnum` |
| `throw new XxxException(...)` | `raise XxxError(...)` |
| `catch (E e) { throw new F(e); }` | `raise F(...) from e` |
| `.csproj` + `dotnet restore` | `pyproject.toml` + `uv sync` |
| `xUnit` / `NUnit` | `pytest` |

---

## 练习方向

1. 让探针超时抛异常，在 `check_all` 中捕获并产出 `UNKNOWN`，而不是让整个命令失败。
2. 加 `--timeout-ms` 参数，用 `functools.partial` 注入探针。
3. 用 `socket` 实现真实 TCP 探针，并在测试中用 `monkeypatch` 替换。
4. 给表格和 JSON 增加 `expected_latency_ms` 列，补测试，观察哪些测试会失败。
5. 引入 mypy / pyright（`uv add --dev mypy`），`uv run mypy src`，修复所有类型问题。
6. 实现 `check-all --fail-on degraded`，让退出码策略可配置。

---

## 验收

- [x] 能读懂现代 Python type hints
- [x] 能使用 Pydantic 建模和校验
- [x] 能写 pytest
- [x] 不依赖教程完成一个小型 CLI

## 本周记录

### 学到了什么

（待填写 —— 建议写：注解 ≠ 校验、Pydantic vs dataclass 的取舍边界、异常链的价值）

### 遇到的问题

（待填写 —— 建议写：第一次 `uv sync` 因缺少 README.md 触发 hatchling 构建失败）

### 关键代码 / Commit

- 项目：`~/ai-agent-24weeks/week1/ai-agent-lab/`
- 重点文件：`src/ai_agent_lab/models.py`、`service.py`、`cli.py`
- 验证：`uv run pytest` → 35 passed
- 本目录尚未 `git init`；建议 Week 1 收尾时初始化并提交首个 commit。

### 下周改进

（待填写）

## 下一步

[[Week-02-Async-FastAPI]]：把本周 `service` 层接到 FastAPI + async。
本周的 `Probe` 注入点即为将来替换成异步 HTTP 客户端的接口预留。
