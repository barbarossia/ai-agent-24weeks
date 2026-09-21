# HomeLab MCP Server (Week 8)

Week 8 — HomeLab MCP Server：将私有基础设施能力以 MCP 接口安全、只读地暴露给 AI Agent。

---

## 设计原则与架构边界

### 1. 严格只读安全边界 (Strict Read-Only)
- 仅提供状态查询与指标观测工具（`list_devices_and_services`, `get_health_status`, `get_basic_metrics`）。
- **杜绝任何写操作**：严禁暴露重启主机、开关容器、修改网络配置等破坏性指令，从协议层切断误操作与 Prompt 注入危害。

### 2. 三种适配器架构 (Adapter Pattern)
- **`MockAdapter` (默认)**：提供脱敏、离线的 HomeLab 样例数据（涵盖 OpenWrt、ESXi、Postgres、Nginx、Transmission），无需任何外部网络或真实设备即可完全独立运行并测试。
- **`RealAdapter`**：通用 HTTP/REST 适配器，通过结构化 JSON 规范（`HOMELAB_CONFIG_JSON` 字符串或 `HOMELAB_CONFIG_FILE` 文件路径，由 Pydantic `RealAdapterConfig` 校验字段和类型）配置，仅发起只读 `GET` 请求，路径可配置。适用于已有统一 REST 导出器/网关的场景。**零凭据硬编码，不持久化或打印 Token**。
- **`OpenWrtAdapter`（真实 OpenWrt 场景）**：针对真实 OpenWrt 路由器的**真实协议实现**——ubus-over-HTTP（`/ubus`，与 LuCI 自身使用的接口完全一致），而非虚构的 REST 接口。仅允许调用固定的只读 ubus 方法白名单（`session.login`、`system.board`、`system.info`、`network.interface.dump`、`network.device.status`），不实现、也不可达任何写操作（重启、接口开关、配置提交等）。详见下方"OpenWrtAdapter：真实 OpenWrt 集成"章节。

---

## MCP 工具清单

| MCP Tool / API | 参数 | 功能描述 | 返回格式 |
|---|---|---|---|
| `session.send_ping()` (协议层) | 无 | **真正的 MCP 协议连接存活检测**：发送 `PingRequest`，成功时返回 `EmptyResult`。由官方 MCP SDK 内建支持，无需自定义工具。 | `mcp.types.EmptyResult` |
| `ping` (应用层工具，可选) | 无 | 应用级自描述状态工具（非协议连通性检查），内部调用 `adapter.ping()` 执行只读连通性检查（`MockAdapter` 恒为可达；`RealAdapter` 发起一次轻量 GET 请求；`OpenWrtAdapter` 执行一次真实的 ubus session 登录；均不抛出异常，返回可达性布尔值），并返回服务名、适配器模式及只读标志 | JSON Object |
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

### 路径可配置（RealAdapter，用于通用 REST 导出器/网关）

`RealAdapter` 默认假设后端提供 `/api/v1/inventory`、`/api/v1/health[/​{target_id}]`、
`/api/v1/metrics/{target_id}` 这样的统一 REST 接口。若你已有自己的导出器/网关服务且路径不同，
`RealAdapterConfig` 把这些路径做成了**可配置模板**：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `inventory_path` | `/api/v1/inventory` | 返回设备/服务清单的 GET 路径 |
| `health_list_path` | `/api/v1/health` | 返回全部目标健康状态的 GET 路径 |
| `health_path_template` | `/api/v1/health/{target_id}` | 单个目标健康状态的 GET 路径模板，必须包含 `{target_id}` 占位符 |
| `metrics_path_template` | `/api/v1/metrics/{target_id}` | 单个目标指标的 GET 路径模板，必须包含 `{target_id}` 占位符 |

> **安全边界**：`RealAdapter` 永远只发起 HTTP GET 请求，不实现任何写操作。

> **安全边界**：以上仅为占位符示例，`base_url` 使用 `.invalid` 保留域名、`auth_token` 为占位字符串。
> 连接或部署到真实 HomeLab 需要显式通过 Human Gate 确认，本仓库默认不启用、不测试真实连接。

---

## OpenWrtAdapter：真实 OpenWrt 集成（ubus-over-HTTP）

`RealAdapter` 假设的统一 REST 接口是一个**占位假设**，真实 OpenWrt 路由器**并不提供**
`/api/v1/...` 这类接口。为了真正对接真实 OpenWrt，本项目额外实现了 `OpenWrtAdapter`
（`HOMELAB_MODE=openwrt`），使用 OpenWrt **原生**的管理协议：**ubus-over-HTTP**——
即 `/ubus` JSON-RPC 2.0 接口，与 LuCI 网页管理界面自身使用的接口完全相同。

调用流程：

1. `POST /ubus`，ubus 方法 `session.login`（匿名 session id
   `00000000000000000000000000000000` + `username`/`password`），换取 `ubus_rpc_session`。
2. 使用该 session id，对以下**固定只读方法白名单**发起 `POST /ubus` 调用：
   - `system.board`（主机名/型号等设备信息 → 资产清单）
   - `system.info`（uptime、load、内存 → 健康状态与指标）
   - `network.interface.dump`（接口列表及 up/down 状态 → 资产清单与健康状态）
   - `network.device.status`（单接口流量计数器 → 指标）

`openwrt_adapter.py` 中的 `_ALLOWED_UBUS_CALLS` 显式列出了以上 5 个只读方法，代码里没有任何
"透传任意 ubus 方法" 的能力，也未实现、不可达任何写方法（`system.reboot`、
`network.interface.up/down`、`uci.commit` 等）。

> **为什么这里允许 POST，而 `RealAdapter` 是 GET-only？** OpenWrt 的 ubus 协议本身就是
> 基于 JSON-RPC 的 `POST` 调用，没有等价的 GET 接口——这是 OpenWrt 自身协议的限制，不是本项目
> 的选择。因此本项目对 `OpenWrtAdapter` 做了一个**明确、狭窄、白名单限定**的例外：仅这 5 个
> 只读 ubus 方法可被调用，且只能通过本文件里固定编码的调用点触发，没有任何把用户输入
> 透传为 ubus object/method 的路径。

配置示例见 [`examples/openwrt_config.example.json`](./examples/openwrt_config.example.json)：

```json
{
  "base_url": "192.168.1.1",
  "username": "root",
  "password": "REPLACE_WITH_YOUR_OPENWRT_PASSWORD",
  "timeout_seconds": 5.0
}
```

```bash
export HOMELAB_MODE=openwrt
export OPENWRT_CONFIG_FILE=./examples/openwrt_config.example.json
uv run homelab-mcp-demo
```

需要路由器开启 ubus/rpcd 的 HTTP 访问（OpenWrt/LuCI 默认已开启），并提供一个在
`/usr/share/rpcd/acl.d/` 中被授权调用上述 object/method 的账号密码。

> **安全边界**：`OpenWrtAdapter` 仅调用上述 5 个只读 ubus 方法，绝不调用任何写方法；凭据仅
> 保存在内存中，不打印、不持久化；ubus session id 仅在 adapter 实例生命周期内缓存。示例文件中
> 的密码为占位符，使用前必须替换为你自己的真实凭据，且不应将真实凭据提交到本仓库。

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
│   ├── models.py               # 数据实体、BaseHomeLabAdapter 抽象基类、RealAdapterConfig/OpenWrtAdapterConfig
│   ├── mock_adapter.py         # MockAdapter (离线脱敏基础设施数据)
│   ├── real_adapter.py         # RealAdapter (只读 HTTP/REST 通用导出器/网关适配器)
│   ├── openwrt_adapter.py      # OpenWrtAdapter (真实 OpenWrt ubus-over-HTTP 适配器，只读方法白名单)
│   ├── server.py               # MCP Server 工具暴露层
│   └── demo_client.py          # 离线演练终端 Client
├── examples/
│   ├── README.md                          # 示例文件用途与使用说明
│   ├── real_adapter_config.example.json   # 通用 REST 场景 JSON 配置示例
│   └── openwrt_config.example.json        # 真实 OpenWrt ubus 场景 JSON 配置示例
└── tests/
    ├── test_homelab_server.py  # Mock/RealAdapter 逻辑与安全边界测试
    ├── test_openwrt_adapter.py # OpenWrtAdapter ubus 协议测试（MockTransport 模拟真实路由器）
    └── test_integration.py     # stdio JSON-RPC MCP 协议端到端集成测试
```
