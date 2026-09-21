# HomeLab MCP Server (Week 8)

Week 8 — HomeLab MCP Server：将私有基础设施能力以 MCP 接口安全、只读地暴露给 AI Agent。

---

## 设计原则与架构边界

### 1. 严格只读安全边界 (Strict Read-Only)
- 仅提供状态查询与指标观测工具（`list_devices_and_services`, `get_health_status`, `get_basic_metrics`）。
- **杜绝任何写操作**：严禁暴露重启主机、开关容器、修改网络配置等破坏性指令，从协议层切断误操作与 Prompt 注入危害。

### 2. 双适配器架构 (Adapter Pattern)
- **`MockAdapter` (默认)**：提供脱敏、离线的 HomeLab 样例数据（涵盖 OpenWrt、ESXi、Postgres、Nginx、Transmission），无需任何外部网络或真实设备即可完全独立运行并测试。
- **`RealAdapter`**：标准 HTTP/REST 适配器，通过结构化 JSON 规范（`HOMELAB_CONFIG_JSON` 字符串或 `HOMELAB_CONFIG_FILE` 文件路径，由 Pydantic `RealAdapterConfig` 校验字段和类型）配置，仅发起只读 `GET` 请求。**零凭据硬编码，不持久化或打印 Token**。

---

## MCP 工具清单

| MCP Tool / API | 参数 | 功能描述 | 返回格式 |
|---|---|---|---|
| `session.send_ping()` (协议层) | 无 | **真正的 MCP 协议连接存活检测**：发送 `PingRequest`，成功时返回 `EmptyResult`。由官方 MCP SDK 内建支持，无需自定义工具。 | `mcp.types.EmptyResult` |
| `ping` (应用层工具，可选) | 无 | 应用级自描述状态工具（非协议连通性检查），内部调用 `adapter.ping()` 执行只读连通性检查（`MockAdapter` 恒为可达；`RealAdapter` 发起一次轻量 GET 请求，不抛出异常，返回可达性布尔值），并返回服务名、适配器模式及只读标志 | JSON Object |
| `list_devices_and_services` | `category?: string` | 列出设备与服务资产清单（支持按分类过滤） | JSON Array (`DeviceOrService`) |
| `get_health_status` | `target_id?: string` | 查询指定目标或全局健康状态、可用性及探针时延 | JSON Array (`HealthStatus`) |
| `get_basic_metrics` | `target_id: string` | 查询目标 CPU、内存、磁盘利用率及网络流量指标 | JSON Object (`BasicMetrics`) |

> **注意**：`ping` MCP Tool 是一个可选的应用层状态自描述工具，**不是** MCP 协议本身的连接性检查。
> 真正的"服务端连接探活"应使用官方 SDK 提供的 `ClientSession.send_ping()`（发送 `PingRequest`，
> 成功时返回 `EmptyResult`），`demo_client.py` 与集成测试均先执行该协议级 ping，再调用四个业务工具。

---

## RealAdapter JSON 配置示例

`RealAdapter` 通过结构化 JSON 配置，而非零散的环境变量。支持三种输入方式（互斥，按以下优先级）：

1. 直接传入 `RealAdapterConfig` 实例（编程调用场景）；
2. 环境变量 `HOMELAB_CONFIG_JSON`：JSON 字符串；
3. 环境变量 `HOMELAB_CONFIG_FILE`：指向 JSON 配置文件的路径。

> 可直接使用的独立 JSON 示例文件位于 [`examples/`](./examples/) 目录：
> [`examples/real_adapter_config.example.json`](./examples/real_adapter_config.example.json)（通用 REST 场景）与
> [`examples/openwrt_config.example.json`](./examples/openwrt_config.example.json)（真实 OpenWrt 场景，见下方"路径可配置"章节）。
> 均为脱敏占位内容，不含真实凭据或真实地址。

JSON 结构（字段由 Pydantic `RealAdapterConfig` 校验）：

```json
{
  "base_url": "http://homelab-api.example.invalid:8080",
  "auth_token": "REPLACE_WITH_SECRET",
  "timeout_seconds": 5.0
}
```

- `base_url`（必填）：真实 HomeLab REST 接口的基础地址。也可以直接填写裸 IP（如 `192.168.1.1` 或 `192.168.1.1:8080`），未带 scheme 时会自动补全为 `http://`。
- `auth_token`（可选）：Bearer Token，仅在内存中用于构造请求头，不打印、不持久化。
- `timeout_seconds`（可选，默认 `5.0`，范围 `0.5–60.0`）：HTTP 请求超时时间。
- `inventory_path` / `health_list_path` / `health_path_template` / `metrics_path_template`（均可选，见下方"路径可配置"章节）。

示例（Python，仅用于本地开发；本仓库不包含真实凭据或真实地址）：

```python
from homelab_mcp_server.real_adapter import RealAdapter

adapter = RealAdapter(config_json='{"base_url": "http://homelab-api.example.invalid:8080", "auth_token": "REPLACE_WITH_SECRET", "timeout_seconds": 5.0}')
```

### 路径可配置：为什么，以及针对 OpenWrt 等真实设备的场景

`RealAdapter` 默认假设后端提供 `/api/v1/inventory`、`/api/v1/health[/​{target_id}]`、
`/api/v1/metrics/{target_id}` 这样的统一 REST 接口——这是一个**占位假设**，并不代表任何真实设备
（例如 OpenWrt 路由器）本身就提供这些路径。

真实 OpenWrt 的原生状态查询接口是 **ubus-over-HTTP**（`/ubus`，JSON-RPC 2.0），典型流程是先
`POST` `session`/`login` 获取 session id，再 `POST` 调用如 `ubus call system board`、
`ubus call system info` 等方法获取只读信息。这种"先登录再 POST 调用"的模式，与本项目为了安全
而设定的**严格只读 GET-only** 边界（已经过 Reviewer 审核批准）是冲突的：本项目不会为了适配
ubus 而引入 POST/JSON-RPC 调用能力。

因此，`RealAdapterConfig` 把这些路径做成了**可配置模板**，而不是硬编码：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `inventory_path` | `/api/v1/inventory` | 返回设备/服务清单的 GET 路径 |
| `health_list_path` | `/api/v1/health` | 返回全部目标健康状态的 GET 路径 |
| `health_path_template` | `/api/v1/health/{target_id}` | 单个目标健康状态的 GET 路径模板，必须包含 `{target_id}` 占位符 |
| `metrics_path_template` | `/api/v1/metrics/{target_id}` | 单个目标指标的 GET 路径模板，必须包含 `{target_id}` 占位符 |

要接入真实 OpenWrt（或其他真实 HomeLab 设备），推荐做法是：在设备前面部署一个**只读的
GET 导出器/网关**（例如一个小型脚本或反向代理，内部完成到 ubus 的 POST/JSON-RPC 转换，只对外
暴露简单的 GET 端点），然后把该导出器的路径填入上述字段。完整可运行示例见
[`examples/openwrt_config.example.json`](./examples/openwrt_config.example.json)：

```json
{
  "base_url": "192.168.1.1",
  "auth_token": null,
  "timeout_seconds": 5.0,
  "inventory_path": "/cgi-bin/exporter/inventory",
  "health_list_path": "/cgi-bin/exporter/health",
  "health_path_template": "/cgi-bin/exporter/health/{target_id}",
  "metrics_path_template": "/cgi-bin/exporter/metrics/{target_id}"
}
```

> ⚠️ **`/cgi-bin/exporter/...` 不是 OpenWrt 自带的路径**：这是一个**虚构的占位路径**，示意
> "假设你自己写了一个导出器脚本并把它部署在这个路径下"。真实 OpenWrt 出厂/默认状态下**并不
> 提供**任何 `/api/v1/...` 或 `/cgi-bin/exporter/...` 风格的只读 REST/GET 接口——你必须自己
> 编写并部署该导出器脚本（把它对内转换成 ubus 的 POST/JSON-RPC 调用，对外只暴露 GET），
> 并把上面的字段改成你自己导出器实际使用的路径，本项目才能真正连上它。

> **安全边界**：本仓库不包含、也不会实现任何 ubus POST/JSON-RPC 调用逻辑；`RealAdapter`
> 永远只发起 HTTP GET 请求。是否在你自己的网络里部署上述导出器/网关，以及该导出器如何安全地
> 完成到真实设备的认证与调用，由你自行负责，超出本仓库范围。

> **安全边界**：以上仅为占位符示例，`base_url` 使用 `.invalid` 保留域名、`auth_token` 为占位字符串。
> 连接或部署到真实 HomeLab 需要显式通过 Human Gate 确认，本仓库默认不启用、不测试真实连接。

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
├── examples/
│   ├── README.md                          # 示例文件用途与使用说明
│   ├── real_adapter_config.example.json   # 通用 REST 场景 JSON 配置示例
│   └── openwrt_config.example.json        # 真实 OpenWrt 场景（自定义路径模板）JSON 配置示例
└── tests/
    ├── test_homelab_server.py  # 适配器逻辑与安全边界测试
    └── test_integration.py     # stdio JSON-RPC MCP 协议端到端集成测试
```
