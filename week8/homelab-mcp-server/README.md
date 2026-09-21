# HomeLab MCP Server (Week 8)

Week 8 — HomeLab MCP Server：将私有基础设施能力以 MCP 接口安全、只读地暴露给 AI Agent。

---

## 设计原则与架构边界

### 1. 严格只读安全边界 (Strict Read-Only)
- 仅提供状态查询与指标观测工具（`list_devices_and_services`, `get_health_status`, `get_basic_metrics`）。
- **杜绝任何写操作**：严禁暴露重启主机、开关容器、修改网络配置等破坏性指令，从协议层切断误操作与 Prompt 注入危害。

### 2. 双适配器架构 (Adapter Pattern)
- **`MockAdapter` (默认)**：提供脱敏、离线的 HomeLab 样例数据（涵盖 OpenWrt、ESXi、Postgres、Nginx、Transmission），无需任何外部网络或真实设备即可完全独立运行并测试。
- **`RealAdapter`**：标准 HTTP/REST 适配器，仅通过环境变量（`HOMELAB_BASE_URL`, `HOMELAB_AUTH_TOKEN`, `HOMELAB_HTTP_TIMEOUT`）配置，仅发起只读 `GET` 请求。**零凭据硬编码**。

---

## MCP 工具清单

| MCP Tool | 参数 | 功能描述 | 返回格式 |
|---|---|---|---|
| `list_devices_and_services` | `category?: string` | 列出设备与服务资产清单（支持按分类过滤） | JSON Array (`DeviceOrService`) |
| `get_health_status` | `target_id?: string` | 查询指定目标或全局健康状态、可用性及探针时延 | JSON Array (`HealthStatus`) |
| `get_basic_metrics` | `target_id: string` | 查询目标 CPU、内存、磁盘利用率及网络流量指标 | JSON Object (`BasicMetrics`) |

---

## 运行与验证

### 1. 安装与同步依赖

```bash
cd week8/homelab-mcp-server
uv sync
```

### 2. 运行自动化 Smoke Tests

运行离线单元测试与基于 stdio 协议的端到端集成测试：

```bash
uv run pytest -v
```

### 3. 运行离线演示 Client

通过标准 stdio 启动 HomeLab MCP Server 并执行全套只读工具调用：

```bash
uv run homelab-mcp-demo
# 或
uv run python -m homelab_mcp_server.demo_client
```

---

## 项目结构

```text
homelab-mcp-server/
├── pyproject.toml              # 依赖声明 (mcp==1.3.0, httpx, pydantic)
├── .python-version             # Python 3.12
├── README.md                   # 架构与只读安全指引
├── src/homelab_mcp_server/
│   ├── __init__.py
│   ├── models.py               # 数据实体与 BaseHomeLabAdapter 抽象基类
│   ├── mock_adapter.py         # MockAdapter (离线脱敏基础设施数据)
│   ├── real_adapter.py         # RealAdapter (只读 HTTP/REST 外部适配器)
│   ├── server.py               # MCP Server 工具暴露层
│   └── demo_client.py          # 离线演练终端 Client
└── tests/
    ├── test_homelab_server.py  # 适配器逻辑与安全边界测试
    └── test_integration.py     # stdio JSON-RPC MCP 协议端到端集成测试
```
