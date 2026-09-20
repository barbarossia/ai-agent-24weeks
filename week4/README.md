# Week 4 — Function / Tool Calling（学习工作区）

本目录是 24 周 AI Agent Engineer 学习计划的 Week 4 工作区，对应笔记：
`01-Projects/AI-Agent/24周学习计划/Week-04-Function-Tool-Calling`。

> 本目录由 Implementer（handoff `function-calling-week4-20260920-001`）在**发现目录原本
> 不存在**后创建。目标目录 `~/ai-agent-24weeks/week4/` 在本次执行前不存在，因此本目录内容
> 均为新增，未覆盖任何既有用户文件。
>
> 按本次 handoff 的授权范围，本周刻意**只做一个最小的端到端例子**：模型请求 → 工具定义 →
> 工具调用 → 工具执行 → 结果返回给模型。不扩展到多 Agent 工作流、生产部署或复杂框架集成
> （那些是 Week 5+ 的主题）。全部用 mock 在本地确定性运行：**无需 API key，不产生任何真实
> 网络请求或费用**。

## 本周覆盖情况

| 本次任务范围要求 | 是否覆盖 | 载体 |
|---|---|---|
| 默认无需真实 API key，走本地 mock | ✅ | `tool-calling-lab/src/tool_calling_lab/mock_model.py`（`MockModel`，纯本地确定性规则） |
| 清晰的运行命令 | ✅ | `tool-calling-lab/README.md`「运行」一节 |
| 完整一轮 function-calling 循环 | ✅ | `tool-calling-lab/src/tool_calling_lab/loop.py`（`run_once`：5 步） |
| 记录实测输出 / 验证结果 | ✅ | `tool-calling-lab/README.md`「验证记录」一节（`pytest` 与 CLI 的真实控制台输出） |

## 目录结构

```text
week4/
├── README.md                     # 本文件：Week 4 总览
└── tool-calling-lab/             # 可运行项目（详见其 README）
    ├── pyproject.toml            # pydantic（参数校验）+ pytest
    ├── .python-version           # 3.12
    ├── README.md                 # 详细讲解 + 运行命令 + 实测验证记录
    ├── src/tool_calling_lab/
    │   ├── tools.py               # 3 个只读 mock 工具：Schema + 实现 + 注册表
    │   ├── mock_model.py         # 确定性 mock 模型（工具选择 + 结果转答案）
    │   ├── loop.py                # 完整的 5 步 function-calling 循环
    │   └── cli.py / __main__.py  # 命令行入口
    └── tests/                     # 18 个用例（工具校验/执行 + 完整循环 + 五步 trace/工具定义断言）
```

## 快速开始

```bash
cd tool-calling-lab
uv sync                       # 安装 Python 3.12 + 依赖
uv run pytest                 # 18 passed
uv run tool-calling-lab       # 运行内置演示问题（无需任何参数/API key）
```

详细说明、运行命令与实测输出见 `tool-calling-lab/README.md`。

## 一句话总结

Week 3 教会"模型只会返回字符串，用 Pydantic 校验结构化输出"；Week 4 把这一课延伸到
"工具"：**工具定义就是给模型看的 JSON Schema，工具调用就是模型返回的一份结构化参数，
工具执行前必须像对待任何不可信输入一样先校验参数，工具失败要变成一条结果消息而不是让
程序崩溃**。本例用一个确定性 mock 模型完整地跑通了这五步，不引入任何框架或真实网络依赖。

下一周（Week 5）会把这"一轮"循环，扩展成可以反复"决策 → 执行 → 观察"的通用 Agent Loop。
