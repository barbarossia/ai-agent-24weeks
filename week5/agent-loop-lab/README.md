# agent-loop-lab

Week 5 — 手写 Agent Loop：一个**最小、可运行、可解释**的多步 ReAct 风格
Agent Loop。全程使用本地确定性 mock：**不需要 API key，不发起任何真实网络请求**。

对应笔记：`01-Projects/AI-Agent/24周学习计划/Week-05-手写-Agent-Loop`。

## 这个例子演示什么

Week 4 的 `tool-calling-lab` 只做一轮（最多一次工具调用）。这一周把它改造成一个
真正可以重复 "思考 → 行动 → 观察" 的通用 Agent Loop，并加入停止条件：

```text
User question
     │
     ▼
┌──> 1. Thought   (模型看到 问题 + 历史 observation，决定下一步)
│         │
│         ▼
│    2. 需要 Action？
│    ├─ 是 → 3. 执行 Tool → 4. Observation ──┐
│    │                                        │
│    +----------------------------------------+  (append 到 history，继续循环)
│
└──> 否 → 5. Final Answer（停止）
```

- **Agent Loop**：`agent_loop.run_agent()` 是核心，不依赖任何框架（不用
  LangGraph），纯 Python `for` 循环 + 显式历史列表。
- **ReAct**：每一步都是 `Thought → Action → Observation` 的循环，`Decision`
  只包含一个动作或一个最终答案，永远不会两者都缺（缺省视为空最终答案，防止
  循环因为模型返回不完整而卡死）。
- **停止条件（Stop Condition）**：
  - 模型自己决定给出最终答案 → `StopReason.FINAL_ANSWER`；
  - 达到 `max_steps` 仍未给出答案 → `StopReason.MAX_STEPS_REACHED`
    （见 `StubbornModel`：一个永远不会满意、永远重新检查同一个工具的
    "顽固" mock 模型，用来证明如果没有这个限制 Agent 就会无限循环）；
  - 达到 `timeout_seconds` 墙钟预算 → `StopReason.TIMEOUT`（时钟通过可注入的
    `clock: Callable[[], float]` 参数传入，测试里用假时钟让超时可复现，
    不用真的 `sleep`）。
- **Tool exception 不会打断循环**：`_execute_action()` 统一捕获三类失败——
  参数校验失败（`pydantic.ValidationError`）、已知的"参数合法但查无此项"
  （`tools.ToolExecutionError`）、以及工具内部**未预期**的 bug（任意其他
  `Exception`，例如 `check_alerting("buggy01")` 故意抛出的
  `RuntimeError`）——全部转换成一条带 `error` 的 `Observation`，循环继续或
  按正常流程收尾，进程绝不会因为一次工具调用崩溃。
- **execution trace**：`AgentTrace.steps` 记录每一步的 thought / action /
  action_input / result / error，可以完整回放"Agent 在想什么、做了什么、
  看到了什么"。

### 多步诊断场景（`Diagnose host <host>`）

这是本例主要的多步演示：

```text
1. get_host_status(host)
     ├─ 状态未知/校验失败 → 提前停止，给出"无法读取状态"的最终答案
     ├─ 状态 = down       → 提前停止，跳过 docker/alert 检查（没必要查一个不可达的主机）
     └─ 状态 = up         → 继续
2. get_docker_status(host)
3. check_alerting(host)     ← buggy01 在这一步故意抛出未预期异常，验证不崩溃
4. 汇总三步观察，给出最终诊断
```

### 单工具问题（向后兼容 Week 4 的行为）

非 "diagnose" 问题（例如 "What is the status of host db01?"）仍然只做一次
工具调用就结束——与 Week 4 的单轮行为一致，证明同一个 Agent Loop 既能做
多步任务也能优雅地退化成单步。

## 运行

```bash
cd week5/agent-loop-lab
uv sync                       # 安装 Python 3.12 + 依赖（pydantic + pytest）
uv run pytest                 # 全部通过
uv run agent-loop-lab         # 运行内置演示问题 + max_steps 安全上限演示
uv run agent-loop-lab "Diagnose host web01"   # 运行自定义问题
uv run agent-loop-lab --schema   # 打印四个工具的 JSON-Schema 定义
```

不需要设置任何环境变量或 API key —— 默认且唯一的路径就是本地 mock。

## 目录结构

```text
agent-loop-lab/
├── pyproject.toml            # pydantic（参数校验）+ pytest；无 HTTP 依赖
├── .python-version           # 3.12
├── src/agent_loop_lab/
│   ├── tools.py              # 4 个工具：参数 Schema + mock 实现 + 工具注册表
│   │                         #   （比 Week 4 多了 check_alerting，专门用来演示
│   │                         #    "未预期工具异常"的处理）
│   ├── react_model.py         # ReactModel.decide()：Thought/Action/FinalAnswer 决策；
│   │                         #   StubbornModel：永不满足的 mock，用来演示 max_steps
│   ├── agent_loop.py          # run_agent()：多步循环本体 + max_steps/timeout/异常处理
│   └── cli.py / __main__.py  # 命令行入口：demo / 自定义问题 / --schema
└── tests/
    ├── test_tools.py          # 参数校验、工具执行、包括 buggy01 的未预期异常
    └── test_agent_loop.py      # 多步诊断链、提前停止、未预期异常不崩溃、
                                 # 单工具兼容、无工具直接回答、
                                 # max_steps 与 timeout（注入假时钟）、history 累积
```

## 验收对照

- [x] 能从代码层解释 Agent 到底是什么 —— 见上方 "这个例子演示什么"，
      `run_agent()` 本身就是最直接的解释：一个显式的 for 循环，没有任何框架魔法。
- [x] 能观察每一步 Tool Call —— `AgentTrace.steps` 完整记录 thought / action /
      action_input / result / error，CLI demo 会逐步打印。
- [x] Agent 不会无限循环 —— `max_steps`（`StubbornModel` 演示 + 测试断言）和
      `timeout_seconds`（注入假时钟的测试断言）两道独立的安全限制。

## 范围声明（刻意不做的事）

- 不使用 LangGraph 或其他 Agent 框架（那是 Week 13 的主题）；
- 不做 Router / Planner-Executor / Multi-Agent（Week 6、Week 21 的主题）；
- 不做 Human-in-the-loop 审批（Week 15 的主题，本例的工具全部只读）；
- 不做持久化 / Checkpoint（Week 14 的主题）。

## 与前后周的连接

- **接 Week 4**：复用同一批只读 mock 工具（`get_host_status` /
  `get_dns_result` / `get_docker_status`），单工具问题的行为与 Week 4 完全一致；
  `Tool.definition()` 的 JSON-Schema 生成方式也保持不变。
- **向 Week 6**：`ReactModel._diagnose_step()` 里那段"先查状态、状态正常才
  继续查 docker、再查 alert"的硬编码顺序，正是 Week 6 要用 Router /
  Planner-Executor 来取代的"if/else 决策"雏形。
- **向 Week 13**：`run_agent()` 里的显式 `history: list[Observation]` 和
  `for` 循环，就是 LangGraph 的 `State` 和 `Graph` 想要抽象、持久化、
  可恢复化的东西。
