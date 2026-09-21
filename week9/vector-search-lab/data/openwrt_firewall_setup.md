# OpenWrt 防火墙与端口转发配置手册

## 防火墙区域与策略设计

OpenWrt 的网络防火墙基于 `nftables`（旧版本基于 `iptables`），通过 UCI 配置文件 `/etc/config/firewall` 进行管理。
核心抽象概念包括区域（zone）、规则（rule）与转发（forwarding）。

典型 HomeLab 区域划分：
- `lan`：受信局域网区域，默认入站策略为 ACCEPT，出站策略为 ACCEPT，转发为 ACCEPT。
- `wan`：非受信外网区域，默认入站策略为 REJECT，出站策略为 ACCEPT，转发为 REJECT，启用 MASQUERADE（SNAT）。
- 跨区域转发策略：允许 `lan` 流量单向流向 `wan`；若需从 `wan` 访问 `lan` 内部服务，必须显式定义目标地址转换（DNAT）规则。

## 端口转发（Port Forwarding / DNAT）

端口转发规则用于将外网 WAN 端口映射到 HomeLab 内网服务器：

```text
config redirect
    option name 'HomeLab-Nginx-HTTP'
    option src 'wan'
    option proto 'tcp'
    option src_dport '8080'
    option dest 'lan'
    option dest_ip '192.168.1.50'
    option dest_port '80'
    option target 'DNAT'
```

关键配置参数说明：
- `src`：源网络区域，通常为 `wan`。
- `src_dport`：外网监听端口，建议使用非标准端口以减少端口扫描风险。
- `dest_ip`：内网目标服务器的静态 IPv4 地址。
- `dest_port`：内网应用真实监听端口。

## 常见故障与排错流程

1. **外网无法访问内网端口**：
   - 检查 ISP 是否分配公网 IP（若为 CGNAT 大内网 IP，需配合 Cloudflare Tunnel 或 IPv6）。
   - 检查 OpenWrt 上级光猫是否开启了桥接模式（Bridge Mode）。
   - 使用 `nft list ruleset` 或 `iptables -nvL` 检查计数器是否有数据包命中。

2. **NAT Loopback（回流环回）失效**：
   - 局域网内部设备使用公网域名/公网 IP 访问内网服务时，需确保防火墙配置中启用了 `option reflection '1'`。
