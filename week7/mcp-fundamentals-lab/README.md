# MCP Fundamentals Lab (Week 7)

Week 7 — MCP Fundamentals：基于官方 Python MCP SDK (`mcp==1.3.0`) 的最小、可运行的 Server/Client 交互样例。

覆盖 MCP 规范三大核心能力：
- **Tools**（工具）：模型可调用的执行函数（支持只读查询及操作型动作）。
- **Resources**（资源）：只读上下文数据与日志/拓扑文件（类似文件系统/URI 读取）。
- **Prompts**（提示词模板）：服务端提供可复用的结构化工作流指令模板。

对应笔记：`01-Projects/AI-Agent/24周学习计划/Week-07-MCP基础`。

---

## 核心概念对比

| MCP 概念 | 角色定位 | 典型场景 | 副作用 / 权限 | 对应示例 |
|---|---|---|---|---|
| **Tools** | 可执行函数 | 查询主机、重启容器、发送命令 | 可能有副作用（需要授权/控制） | `get_host_status`, `reboot_host` |
| **Resources** | 只读上下文与数据 | 读取集群拓扑、日志流、配置文件 | 纯只读，幂等，模型不能随意写入 | `homelab://topology`, `homelab://logs/{host}` |
| **Prompts** | 预置工程提示模板 | 标准化排障流程、SRE 诊断指引 | 无副作用，指导 Agent 规范化决策 | `diagnose_host_prompt` |

---

## 快速运行与验证

### 1. 同步依赖

使用 `uv` 安装固定版本 `mcp==1.3.0`：

```bash
cd week7/mcp-fundamentals-lab
uv sync
```

### 2. 运行自动化 Smoke Test

```bash
uv run pytest -v
```

### 3. 运行 Client 交互演练

Client 会启动 Server 进程并通过标准输入输出（`stdio`）完成 JSON-RPC 握手、工具调用、资源读取与提示词生成全流程：

```bash
uv run mcp-client
# 或
uv run python -m mcp_fundamentals_lab.client
```

---

## 项目代码结构

```text
mcp-fundamentals-lab/
├── pyproject.toml              # 固定依赖 mcp==1.3.0
├── .python-version             # Python 3.12
├── README.md                   # 概念说明与操作指引
├── src/mcp_fundamentals_lab/
│   ├── __init__.py
│   ├── server.py               # FastMCP Server (Tools, Resources, Prompts)
│   └── client.py               # ClientSession, stdio_client, 完整交互演示
└── tests/
    └── test_mcp.py             # 自动化生命周期集成与冒烟测试
```
