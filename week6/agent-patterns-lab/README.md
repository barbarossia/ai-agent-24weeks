# Agent Patterns Lab (Week 6)

Week 6 — 常见 Agent 架构模式与适用边界（Agent Patterns）。

本项目基于纯 Python 标准库与确定性 Mock 数据，实现并演示 4 类经典架构模式。**无需 API Key、无需外部网络或重量级依赖**。

对应笔记：`01-Projects/AI-Agent/24周学习计划/Week-06-Agent-Patterns`。

---

## 4 类核心架构模式对照

| 模式 | 对应实现 | 适用边界 (When to use) | 反模式 (Anti-patterns) |
|---|---|---|---|
| **1. 单 Agent 工具调用** | `pattern1_single_tool.py` | 边界清晰、上下文单一、1-5 个工具的交互式动态调用 | 给单 Agent 塞入数十个跨领域的工具，导致上下文污染与幻觉 |
| **2. 顺序流水线** | `pattern2_pipeline.py` | 确定性的多阶段转换（收集 -> 分析 -> 报告），执行顺序不可变 | 将高度开放探索的任务硬套入静态流水线；或对确定性流程过度引入动态循环 |
| **3. 路由与分流** | `pattern3_router.py` | 任务意图明显属于不同垂直专业领域（网络/容器/主机），先分流再处理 | 嵌套多层庞杂路由树；只有 2 个简单工具却强行增加分流层（增加延迟与成本） |
| **4. 监督者-子 Agent** | `pattern4_supervisor.py` | 复杂任务拆解、多专家角色协同（诊断专家 + 审计合规专家）、结果综合汇聚 | 杀鸡用牛刀：对简单单点查询使用 Supervisor + 多个 Worker，带来级联故障和高延迟 |

---

## 运行与验证

### 1. 安装与同步依赖 (uv)

```bash
cd week6/agent-patterns-lab
uv sync
```

### 2. 统一 Smoke Test (pytest)

```bash
uv run pytest -v
```

### 3. 分别运行各模式独立入口

各模式均具备独立 entrypoint：

```bash
# 模式 1: 单 Agent 工具调用
uv run pattern-single
# 或
uv run python -m agent_patterns_lab.pattern1_single_tool

# 模式 2: 顺序流水线
uv run pattern-pipeline
# 或
uv run python -m agent_patterns_lab.pattern2_pipeline

# 模式 3: 路由与分流
uv run pattern-router
# 或
uv run python -m agent_patterns_lab.pattern3_router

# 模式 4: 监督者-子 Agent
uv run pattern-supervisor
# 或
uv run python -m agent_patterns_lab.pattern4_supervisor

# 一键运行全部模式演练
uv run agent-patterns-lab
```

---

## 项目结构

```text
agent-patterns-lab/
├── pyproject.toml
├── .python-version
├── README.md
├── src/agent_patterns_lab/
│   ├── __init__.py
│   ├── __main__.py
│   ├── common.py                # 基础数据结构与 Mock 数据源
│   ├── pattern1_single_tool.py  # 模式 1：单 Agent 工具调用
│   ├── pattern2_pipeline.py     # 模式 2：顺序流水线
│   ├── pattern3_router.py       # 模式 3：路由与分流
│   ├── pattern4_supervisor.py   # 模式 4：监督者-子 Agent 协同
│   └── cli.py                   # 统一演练 CLI
└── tests/
    └── test_patterns.py         # 针对 4 类模式的全面测试套件
```
