# HomeLab Docker 容器与网络管理手册

## 容器架构与核心服务编排

HomeLab 环境中使用 Docker 与 Docker Compose 运行各种轻量级服务。
核心支撑服务矩阵：
- **Nginx Proxy Manager (NPM)**：反向代理网关，自动申请与续期 Let's Encrypt SSL/TLS 证书，管理二级域名路由。
- **PostgreSQL + pgvector**：向量数据库与通用关系型存储，支撑 AI Agent 知识库检索与持久化状态存储。
- **Transmission / qBittorrent**：下载服务，通常绑定专用 VPN 容器网络以确保网络隔离与隐私。
- **Prometheus + Grafana**：度量指标收集与可视化仪表盘，监控节点 CPU、内存与容器状态。

## 网络驱动设计与隔离

Docker 原生提供多种网络驱动：
1. **Bridge 网络**：默认隔离网络，同一 bridge 内部容器可通过容器名实现 DNS 解析。
2. **Macvlan 网络**：让容器直接接入物理局域网并获取独立局域网 IP（例如与 OpenWrt 处于同一网段），适用于 Pi-hole、AdGuard Home 或旁路由服务。
3. **Host 模式**：直接共享宿主机网络栈，避免 NAT 性能损耗，但存在端口冲突风险。

## 健康检查与运维监控

容器生产化运维要求配置声明式健康检查（Healthcheck）：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
```

当容器发生崩溃或探针失败时，`unless-stopped` 重启策略能够保证服务自动恢复。
通过 `docker stats` 可实时观察容器的 CPU、内存占用及网络 I/O 速率。
