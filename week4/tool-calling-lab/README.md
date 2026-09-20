# tool-calling-lab

Week 4 — Function / Tool Calling：一个**最小、可运行、可解释**的端到端函数调用（Function
Calling / Tool Calling）例子。全程使用本地确定性 mock：**不需要 API key，不发起任何真实
网络请求**。

对应笔记：`01-Projects/AI-Agent/24周学习计划/Week-04-Function-Tool-Calling`。

## 这个例子演示什么

一次完整的 function-calling 闭环，只做一轮（不做多步 Agent Loop，那是 Week 5 的主题）：

```text
User question
     │
     ▼
1. Model request            ← 问题 + 工具定义（JSON Schema）一起交给模型
     │
     ▼
2. Tool call decision        ← 模型返回 tool_call: {name, arguments}（或直接回答）
     │
     ▼
3. Tool execution             ← 先用 Pydantic 校验参数，再跑本地 mock 后端
     │
     ▼
4. Tool result / error 返回给模型
     │
     ▼
5. Final answer                ← 模型根据工具结果生成最终自然语言回复
```

- **Model request / Tool definition**：`tools.py` 里每个 `Tool` 都能渲染出一个
  OpenAI 风格的 `{"type": "function", "function": {...}}` 定义（`parameters` 直接来自
  Pydantic 的 `model_json_schema()`），这与真实模型 API 收到的 `tools=[...]` 形状一致。
- **Model（mock）**：`mock_model.py` 里的 `MockModel` 用关键词 + 正则**确定性**地模拟
  "模型选工具"和"模型读工具结果生成回答"这两步——没有随机性，方便测试和讲解，但接口形状
  （`tool_call` / `content`）与真实模型响应一致，换成真实 provider 时上层循环代码不需要改。
- **Tool execution**：三个只读 mock 工具，数据来自进程内字典，不访问真实系统：
  - `get_host_status(host)` — 查询 mock 主机的上/下线状态
  - `get_dns_result(domain)` — 查询 mock DNS 记录
  - `get_docker_status(host)` — 查询 mock 容器状态
- **不崩溃**：无效参数（`ValidationError`）和"参数合法但查无此项"（`ToolExecutionError`，
  例如未知主机）都在 `loop.py` 里被捕获，转换成一条 tool-error 结果继续走完整个循环，而不是
  让程序抛出未处理异常。

## 运行

```bash
cd week4/tool-calling-lab
uv sync                       # 安装 Python 3.12 + 依赖（pydantic + pytest）
uv run pytest                 # 16 passed
uv run tool-calling-lab       # 运行内置的 5 个演示问题（无需任何参数/API key）
uv run tool-calling-lab "What is the status of host web01?"   # 运行自定义问题
uv run tool-calling-lab --schema   # 打印三个工具的 JSON-Schema 定义
```

不需要设置任何环境变量或 API key —— 默认且唯一的路径就是本地 mock。

## 目录结构

```text
tool-calling-lab/
├── pyproject.toml            # pydantic（参数校验）+ pytest；无 HTTP 依赖
├── .python-version           # 3.12
├── src/tool_calling_lab/
│   ├── tools.py              # 3 个工具：参数 Schema + mock 实现 + 工具注册表
│   ├── mock_model.py         # 确定性 mock 模型：request() / respond_with_tool_result()
│   ├── loop.py                # run_once()：完整的 5 步函数调用循环 + LoopTrace
│   └── cli.py / __main__.py  # 命令行入口：demo / 自定义问题 / --schema
└── tests/
    ├── test_tools.py          # 参数校验、未知字段拒绝、工具执行、JSON Schema 形状
    └── test_loop.py           # 三个工具各自被正确选中、未知主机报错不崩溃、无工具时直接回答
```

## 验证记录（实测输出）

环境：Windows / `uv 0.11.32` / `uv run python 3.12.13` / `pydantic 2.13.5` / `pytest 9.1.1`。

### `uv run pytest -v`

```text
collected 16 items

tests\test_loop.py ......                                                [ 37%]
tests\test_tools.py ..........                                           [100%]

============================= 16 passed in 1.72s ==============================
```

### `uv run tool-calling-lab`（内置 5 个演示问题，逐字实测输出）

```text
Running built-in demo questions (no API key, fully local mock):

=== Question: What is the status of host web01?
  1. model request (question + tool definitions sent to model)
  2. model chose tool call: get_host_status({'host': 'web01'})
  3. tool execution (arguments validated, then tool runs)
  4. tool result returned to model: {'host': 'web01', 'status': 'up', 'latency_ms': 12}
  5. model produced final answer from the tool result
  -> Final answer: Host 'web01' is up (latency 12 ms).

=== Question: Check docker containers on host db01
  1. model request (question + tool definitions sent to model)
  2. model chose tool call: get_docker_status({'host': 'db01'})
  3. tool execution (arguments validated, then tool runs)
  4. tool result returned to model: {'host': 'db01', 'containers': [{'name': 'postgres', 'state': 'running'}]}
  5. model produced final answer from the tool result
  -> Final answer: Docker containers on 'db01': postgres=running.

=== Question: Resolve DNS for example.com
  1. model request (question + tool definitions sent to model)
  2. model chose tool call: get_dns_result({'domain': 'example.com'})
  3. tool execution (arguments validated, then tool runs)
  4. tool result returned to model: {'domain': 'example.com', 'resolved_ip': '93.184.216.34', 'ttl': 300}
  5. model produced final answer from the tool result
  -> Final answer: 'example.com' resolves to 93.184.216.34 (ttl 300s).

=== Question: What is the status of host gateway99?
  1. model request (question + tool definitions sent to model)
  2. model chose tool call: get_host_status({'host': 'gateway99'})
  3. tool execution (arguments validated, then tool runs)
  4. tool result returned to model: error -> unknown host: 'gateway99'
  5. model produced final answer from the tool result
  -> Final answer: I tried to call get_host_status but it failed: unknown host: 'gateway99'

=== Question: Tell me a joke
  1. model request (question + tool definitions sent to model)
  2. model responded directly (no tool needed)
  -> Final answer: I don't have a tool for that question. Try asking about a host's status, its docker containers, or DNS resolution for a domain.
```

## 验收对照

- [x] 不需要真实 API key，默认即走本地 mock —— `mock_model.MockModel` 是唯一路径，
      没有任何网络客户端依赖。
- [x] 提供清晰的运行命令 —— 见上方"运行"一节。
- [x] 演示完整的一轮 function-calling 循环 —— `loop.run_once()` 的 5 步，
      对应 model request → tool definition → tool call → tool execution → result returned。
- [x] 记录实测输出 —— 见"验证记录"一节（`pytest` 与 `tool-calling-lab` 的真实控制台输出）。

## 范围声明（刻意不做的事）

按本次任务范围要求，本例**刻意保持最小**，不包含：

- 多步 / 多 Agent 工作流（那是 Week 5 手写 Agent Loop、Week 6 Agent Patterns、
  Week 21 Multi-Agent 的主题）；
- 生产部署（Docker、CI/CD 等，Week 23 的主题）；
- 复杂框架集成（LangGraph 等，Week 13 的主题）；
- 超时 / 重试 / 幂等性的完整工程实现（Week 4 课程大纲提到，但会在后续更贴近生产的迭代中
  再补——本例只做了"参数校验失败/工具执行失败不崩溃"这一项最基础的健壮性）。

## 与前后周的连接

- **接 Week 3**：工具定义的 `parameters` 直接复用 Pydantic `model_json_schema()`，
  与 Week 3 的 Structured Output 是同一套机制；`ToolCall` 就是"角色为 tool 的结构化输出"。
- **向 Week 5**：`loop.run_once()` 只做一轮。Week 5 会把它改造成可以重复
  "decide → act → observe" 的通用 Agent Loop，并加入 `max_steps` / 停止条件。
