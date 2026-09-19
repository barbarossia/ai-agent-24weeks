# ai-agent-lab — Week 1（Python Backend 基础）

> 24 周 AI Agent Engineer 学习计划的第一个可运行项目。
> 主题：**typing / dataclass / Pydantic / 异常处理 / 虚拟环境与包管理 / pytest**。
>
> 目标不是"学完语法"，而是产出一个 **typed、可测试、可复用** 的小型 CLI，
> 为后续 Week 2（FastAPI）、Week 3（LLM API）打地基。

---

## 1. 它是什么

一个 **HomeLab 主机状态检查 CLI**：读取主机清单（JSON）→ 用 Pydantic 校验 →
执行（模拟）健康检查 → 输出表格或 JSON → 返回有意义的退出码。

```
inventory.json ──▶ Pydantic 校验 ──▶ Host 对象 ──▶ Probe 探针 ──▶ CheckResult
                                                                     │
                                                          ┌──────────┴──────────┐
                                                          ▼                     ▼
                                                     文本表格                JSON 输出
```

为什么选这个题目：它天然包含"外部数据边界（校验）+ 业务规则 + I/O"三层，
正是后端代码的缩影；同时也是最终 HomeLab SRE Agent 的最小前身。

---

## 2. 环境准备（使用 uv 管理 Python 与依赖）

本项目用 [uv](https://docs.astral.sh/uv/) 管理 **Python 版本**和**依赖**，
不用 `pip install` 直接装包。

```bash
cd week1/ai-agent-lab

# 1) 安装/确认项目锁定的 Python（由 .python-version 指定）
uv python install

# 2) 根据 pyproject.toml + uv.lock 创建 .venv 并安装依赖
uv sync

# 3) 查看解析结果
uv tree
```

关键文件：

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 项目元数据 + 依赖声明（单一事实来源） |
| `uv.lock` | 精确锁定所有依赖版本 → 可复现 |
| `.python-version` | 锁定 Python 版本（本仓库为 `3.11`） |
| `.venv/` | uv 生成的虚拟环境（已被 `.gitignore` 忽略） |

> C# 对照：`pyproject.toml` ≈ `.csproj`；`uv.lock` ≈ `packages.lock.json`；
> `.venv` ≈ 项目级 `obj/` + NuGet 还原结果；`uv sync` ≈ `dotnet restore`。

---

## 3. 运行方式

```bash
# 列出主机
uv run ai-agent-lab list

# 检查单台主机（JSON 输出）
uv run ai-agent-lab --json check openwrt-01

# 检查全部并汇总
uv run ai-agent-lab check-all

# 使用自定义清单
uv run ai-agent-lab --inventory examples/inventory.json check-all

# 不使用 console script 也可以：
uv run python -m ai_agent_lab check-all
```

预期输出（`check-all`，节选）：

```
HOST          KIND      STATUS        LATENCY  MESSAGE
-----------------------------------------------------
esxi-01       esxi      UP            117ms    ok
docker-01     docker    UP             78ms    ok
openwrt-01    openwrt   UP             29ms    ok
nas-01        host      UP             58ms    ok

summary: 4 up, 0 degraded, 0 down, 0 unknown => HEALTHY
```

退出码约定：

| 退出码 | 含义 |
|---|---|
| `0` | 成功且整体健康 |
| `1` | 检查完成，但存在 `DOWN`（可直接用于 CI 判断） |
| `2` | 输入/数据错误（清单非法、主机不存在） |
| `3` | 检查执行失败（探针抛异常） |

---

## 4. 代码结构

```text
ai-agent-lab/
├── pyproject.toml          # 依赖 + 工具配置 + 入口点
├── uv.lock                 # 锁文件
├── .python-version         # Python 版本
├── README.md               # 本文件
├── examples/inventory.json # 示例清单
├── src/ai_agent_lab/
│   ├── __init__.py         # 包版本
│   ├── __main__.py         # python -m ai_agent_lab
│   ├── py.typed            # 声明本包带类型信息
│   ├── errors.py           # 自定义异常层级
│   ├── models.py           # Pydantic 模型 + dataclass + StrEnum
│   ├── service.py          # 业务逻辑（不依赖 CLI）
│   └── cli.py              # argparse + 输出渲染
└── tests/
    ├── conftest.py         # 共享 fixtures
    ├── test_models.py      # 模型校验测试
    ├── test_service.py     # 业务逻辑测试
    └── test_cli.py         # CLI 行为 / 退出码测试
```

分层要点：`cli → service → models`。`service` 不认识命令行，因此未来可以
被 FastAPI / MCP Server / 测试直接复用。

---

## 5. 逐模块讲解

### 5.1 `models.py` — 外部数据边界用 Pydantic，内部值对象用 dataclass

**目的**：把"从 JSON 进来的不可信数据"变成"程序内可信的强类型对象"。

关键概念：

- **type hints 默认不校验**。`def f(x: int)` 传入字符串也不会报错；运行时校验
  需要 Pydantic 这样的库把注解变成校验器。
- `Annotated[str, Field(pattern=...)]` 定义**受限字符串类型**（主机名），
  一份定义多处复用 —— 等价于 C# 的 value object。
- `model_config = ConfigDict(frozen=True, extra="forbid")`：实例不可变 +
  拒绝未知字段（拼错配置不会被静默忽略）。
- `field_validator`：字段级归一化（tags 去空格/去重/排序）。
- `model_validator(mode="after")`：跨字段校验（主机名唯一）。

对照示例：

```python
class Host(BaseModel):                    # ← 边界：校验外部数据
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Hostname
    kind: HostKind
    ...

@dataclass(frozen=True, slots=True)
class CheckSummary:                        # ← 内部：轻量不可变值对象
    total: int
    up: int
    ...
```

何时用哪个？
- 数据来自用户/文件/网络/LLM → **Pydantic**（要校验、要转换）。
- 数据只在代码内部流转、形状已知 → **dataclass**（更轻、更快、无依赖）。

### 5.2 `errors.py` — 一棵可被分类捕获的异常树

- `AiAgentLabError` 为根，下分 `InventoryError` / `HostNotFoundError` /
  `CheckFailedError`。
- `raise X from exc` 保留**异常链**（C# 的 InnerException）。
- 异常携带结构化字段（如 `exc.hostname`），上层无需解析错误字符串。

### 5.3 `service.py` — 业务逻辑 + 依赖注入

- `load_inventory` 把文件不存在 / JSON 语法错 / schema 校验错**三层错误**
  统一包装成 `InventoryError`，调用方只需处理一种领域异常。
- `Probe = Callable[[Host], int]` 定义探针协议；`default_probe` 用
  `hashlib` 从主机名派生**确定性**延迟 —— 不访问网络，测试不会 flaky。
- `check_host` 捕获探针异常并包装为 `CheckFailedError`。
- `classify` 用清晰的边界规则把延迟映射为 `UP / DEGRADED / DOWN`。

> C# 对照：`Probe` ≈ `Func<Host, int>`；参数默认值注入 ≈ 构造函数注入的精简版。

### 5.4 `cli.py` — 只做 I/O 与退出码映射

- `argparse` 定义 `list` / `check` / `check-all` 子命令。
- `main(argv) -> int`：返回退出码，**可被测试直接调用**，无需起子进程。
- 把领域异常映射为退出码，保证用户看到干净的错误信息而不是 traceback。

---

## 6. 测试

```bash
uv run pytest            # 全部测试
uv run pytest -v         # 详细
uv run pytest tests/test_service.py::test_classify_boundaries -v
```

测试覆盖：
- **模型**：合法/非法主机名、tags 归一化、未知字段拒绝、不可变性、重名检测。
- **业务**：`classify` 的 5 个边界值、探针注入、异常包装、清单三层错误、汇总。
- **CLI**：子命令输出、JSON 可解析、未知主机返回 2、非法清单返回 2、
  存在 DOWN 时返回 1（用 `monkeypatch` 构造场景）。

`uv run pytest -q` 预期：所有测试通过（见 `../notes/` 中的验证记录）。

---

## 7. 练习方向（从模仿到独立）

1. **加一个 `HealthStatus.UNKNOWN` 的真实来源**：让探针在超时时抛异常，
   在 `check_all` 中捕获并产出 `UNKNOWN`，而不是让整个命令失败。
2. **加 `--timeout-ms` 参数**：用 `argparse` 传入，再通过 `functools.partial`
   注入探针。体会"参数 → 依赖"的传递链。
3. **换掉 `default_probe`**：实现一个真的 `socket` TCP 连接探针（注意超时），
   并用 `monkeypatch` 在测试里替换它。
4. **加一列 `expected_latency_ms`**：修改表格渲染与 JSON，并补测试。
   体会"加字段时哪些测试会失败"。
5. **引入 mypy/pyright**：`uv add --dev mypy`，运行 `uv run mypy src`，
   修复所有类型问题。验收标准之一就是"能读懂现代 type hints"。
6. **实现 `check-all --fail-on degraded`**：让退出码策略可配置。

---

## 8. 常见错误与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: ai_agent_lab` | 没装项目 / 没激活环境 | `uv sync`，并用 `uv run ...` |
| `Readme file does not exist: README.md` | `pyproject.toml` 声明了 readme 但文件缺失 | 补 `README.md` |
| `Address already in use` | 与本项目无关（Week 2 才会出现） | — |
| `ValidationError` | 输入数据不符合 schema | 看错误里的字段名与约束 |
| `error: 'xxx' not found in inventory` | 主机名不在清单 | 先 `list` 确认拼写 |

---

## 9. C# / .NET → Python 速查

| C# / .NET | Python（本项目） |
|---|---|
| `record` / DTO | `@dataclass` / Pydantic `BaseModel` |
| `DataAnnotations` / FluentValidation | Pydantic `Field` / validators |
| `Nullable<T>` | `T | None` |
| `Task<T>` | `async def -> T`（Week 2） |
| `Func<Host,int>` | `Callable[[Host], int]` |
| `enum` | `enum.StrEnum` |
| `throw new XxxException(...)` | `raise XxxError(...)` |
| `catch (E e) { throw new F(e); }` | `raise F(...) from e` |
| `.csproj` + `dotnet restore` | `pyproject.toml` + `uv sync` |
| `xUnit` / `NUnit` | `pytest` |
