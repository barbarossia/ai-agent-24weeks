# Week 1 — Python Backend 基础（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 1 工作区，对应笔记：
`01-Projects/AI-Agent/24周学习计划/Week-01-Python-Backend基础`。

> 本目录由 Implementor（handoff H001）在**发现目录原本不存在**后创建。
> 目标目录 `~/ai-agent-24weeks/week1/` 在本次执行前不存在，因此本目录内容
> 均为新增，未覆盖任何既有用户文件。

---

## 本周覆盖情况（对照课程大纲）

| 大纲要求 | 本目录是否覆盖 | 载体 |
|---|---|---|
| typing / type hints | ✅ | `ai-agent-lab/src/ai_agent_lab/*.py` 全量类型标注 |
| dataclass | ✅ | `models.CheckSummary`（对比 Pydantic） |
| Pydantic | ✅ | `models.Host` / `Inventory` / `CheckResult` |
| exception handling | ✅ | `errors.py` 异常树 + 三层错误包装 + 退出码 |
| virtualenv / 包管理 | ✅ | `uv` + `pyproject.toml` + `uv.lock` + `.python-version` |
| pytest | ✅ | `tests/` 35 个用例（模型/业务/CLI） |
| C# → Python 映射 | ✅ | 两个 README 的对照表 |
| 实战：typed CLI + 测试 | ✅ | `ai-agent-lab`（HomeLab 主机状态检查 CLI） |

### 尚未覆盖（留作练习，见 `ai-agent-lab/README.md` 第 7 节）

- mypy / pyright 静态类型检查接入（验收标准"能读懂 type hints"的强化）
- 真实网络探针（TCP/HTTP），当前为确定性模拟探针
- `logging` 替代 `print`
- 覆盖率报告（`pytest --cov`）

---

## 目录结构

```text
week1/
├── README.md                      # 本文件：Week 1 总览
├── ai-agent-lab/                  # 可运行项目（见其 README）
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .python-version
│   ├── README.md                  # 详细讲解 + 运行 + 练习
│   ├── examples/inventory.json
│   ├── src/ai_agent_lab/
│   └── tests/
└── notes/
    └── Week-01-Python-Backend基础.md   # 交给 Knowledge 的笔记草稿副本
```

> Obsidian 笔记草稿的**权威副本**位于本 handoff 的
> `evidence/Week-01-Python-Backend基础.md`；`notes/` 下只是同内容的工作副本，
> 便于在项目内直接阅读。正式 vault 笔记由 Knowledge 阶段写入。

---

## 快速开始

```bash
cd ai-agent-lab
uv sync                 # 安装 Python 3.11 + 依赖（按 uv.lock）
uv run pytest           # 35 passed
uv run ai-agent-lab check-all
```

---

## 一句话总结

Week 1 把一个"看起来懂了"的语法清单，落成了一个**分层清晰、可测试、
可复用**的真实小项目：Pydantic 守边界，dataclass 做内部值对象，
异常树统一错误语义，uv 锁定环境，pytest 保护行为。

下一周（Week 2）会把这个项目的 `service` 层接到 **FastAPI + async** 上，
本周的 `Probe` 注入点正是为将来替换成异步 HTTP 客户端预留的。
