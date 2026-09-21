# OpenWrt ubus-over-HTTP 接口使用指南

## 概述与架构原理

OpenWrt 的统一总线（micro bus architecture，简称 ubus）是系统内部进程间通信（IPC）的核心通道。
为了支持 Web 管理界面（LuCI）及远程 API 调用，OpenWrt 提供了 `rpcd` 守护进程，通过 HTTP POST 暴露了 JSON-RPC 2.0 规范的 `ubus-over-HTTP` 接口。
默认访问端点为 `/ubus`。

外部客户端通过发送标准 JSON-RPC 请求，可以调用注册在 ubus 总线上的各类对象（object）与方法（method）。
在 HomeLab 环境中，AI Agent 通过只读调用 ubus 接口，能够安全、实时地获取路由器的网络拓扑、接口速率、无线状态和系统硬件指标。

## 认证与会话管理

访问受保护的 ubus 方法前，必须首先调用 `session.login` 换取有效的会话标识符（ubus_rpc_session）。

登录请求格式如下：
- RPC 方法：`call`
- 目标对象：`session`
- 目标方法：`login`
- 关键参数：`username`、`password`
- 匿名会话初始 ID：`00000000000000000000000000000000`

成功返回后，响应体包含 `ubus_rpc_session`（32 位十六进制字符串）及 `timeout` 有效期。后续所有受保护请求必须在参数首位携带该 session ID。
若 session 过期，ubus 服务端将返回错误码 `-32002`（Access Denied），调用方应自动触发重新登录。

## 只读查询接口清单

为了确保基础设施安全，生产和 HomeLab 环境均应配置严格的只读调用白名单：

1. `system.board`：获取设备型号、CPU 架构、内核版本及固件发布信息。
2. `system.info`：获取系统开机运行时间（uptime）、当前负载（load average）、内存总量与空闲量。
3. `network.interface.dump`：枚举所有网络接口（wan, lan, wireguard），返回接口状态（up/down）、IP 地址与网关。
4. `network.device.status`：针对指定物理设备（如 eth0），查询收发数据包（rx_bytes, tx_bytes）及丢包计数。

## 安全与防护边界

严禁在客户端直接暴露任意 ubus 命令透传能力。写操作（如 `system.reboot`、`network.interface.down`、`uci.commit`）必须从代码逻辑上彻底阻断。
所有外部输入必须经过严格的参数白名单校验，防止通过恶意参数注入破坏网络稳定性。
