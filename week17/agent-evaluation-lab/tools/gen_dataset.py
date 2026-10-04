"""Deterministic generator for the Week 17 golden dataset (30 sanitized records).

Usage: ``uv run python tools/gen_dataset.py`` writes ``data/golden_eval.jsonl``.
No network, model, database or device access. IDs are W17-{NET,DOC,ESX}-NNN.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "golden_eval.jsonl"

# (question, required_source, [knowledge rows], answer tokens)
NETWORK = [
    ("网络延迟突增时应先检查什么？", "fixture/runbooks/network-latency.md",
     [("fixture/runbooks/network-latency.md", "Network > Latency", "先查看 WAN 丢包与 DNS 解析耗时，再检查上游代理与出口路由。", 0.83)],
     ["延迟", "丢包", "DNS"]),
    ("如何确认 HomeLab 的 WAN 出口是否正常？", "fixture/runbooks/wan-egress.md",
     [("fixture/runbooks/wan-egress.md", "WAN > Egress", "检查网关 WAN 口状态、默认路由与出口丢包率。", 0.81)],
     ["WAN", "路由", "丢包"]),
    ("DNS 解析失败的第一步排查是什么？", "fixture/runbooks/dns-troubleshooting.md",
     [("fixture/runbooks/dns-troubleshooting.md", "DNS > Troubleshooting", "先确认上游 DNS 可达，再检查本地缓存与解析响应时间。", 0.79)],
     ["DNS", "缓存", "解析"]),
    ("路由器 CPU 占用过高应如何处理？", "fixture/runbooks/router-cpu.md",
     [("fixture/runbooks/router-cpu.md", "Router > CPU", "查看连接跟踪数量与流量整形规则，排除异常会话。", 0.77)],
     ["路由", "CPU", "连接"]),
    ("如何验证代理链路的连通性？", "fixture/runbooks/proxy-connectivity.md",
     [("fixture/runbooks/proxy-connectivity.md", "Proxy > Connectivity", "逐跳测试每一段代理的端口可达性与握手耗时。", 0.80)],
     ["代理", "端口", "握手"]),
    ("出口 NAT 表接近上限时应先做什么？", "fixture/runbooks/nat-table.md",
     [("fixture/runbooks/nat-table.md", "NAT > Table", "先统计会话数量并缩短空闲超时，再考虑扩容。", 0.76)],
     ["NAT", "会话", "超时"]),
    ("如何定位偶发的网络抖动？", "fixture/runbooks/network-jitter.md",
     [("fixture/runbooks/network-jitter.md", "Network > Jitter", "记录抖动时段并与链路负载、无线信道干扰对照。", 0.82)],
     ["抖动", "负载", "干扰"]),
    ("防火墙规则导致流量被丢弃时怎么查？", "fixture/runbooks/firewall-drop.md",
     [("fixture/runbooks/firewall-drop.md", "Firewall > Drops", "查看丢弃计数与命中规则编号，确认方向与接口。", 0.78)],
     ["防火墙", "丢弃", "规则"]),
    ("链路聚合接口异常时先看什么？", "fixture/runbooks/link-aggregation.md",
     [("fixture/runbooks/link-aggregation.md", "Network > Bonding", "确认成员口状态与聚合模式配置一致。", 0.75)],
     ["聚合", "成员", "链路"]),
    ("如何检查 DHCP 地址池是否耗尽？", "fixture/runbooks/dhcp-pool.md",
     [("fixture/runbooks/dhcp-pool.md", "DHCP > Pool", "统计已分配租约与剩余地址，检查异常占用。", 0.79)],
     ["DHCP", "租约", "地址池"]),
]

DOCKER = [
    ("某个容器反复重启时如何排查？", "fixture/runbooks/docker-restart.md",
     [("fixture/runbooks/docker-restart.md", "Docker > Restart", "查看容器退出码与最近日志，确认健康检查与依赖服务。", 0.84)],
     ["容器", "重启", "日志"]),
    ("镜像拉取失败的第一步是什么？", "fixture/runbooks/docker-pull.md",
     [("fixture/runbooks/docker-pull.md", "Docker > Pull", "先确认仓库地址与网络出站，再检查镜像标签是否存在。", 0.80)],
     ["镜像", "拉取", "仓库"]),
    ("容器内存占用异常增长如何处理？", "fixture/runbooks/docker-memory.md",
     [("fixture/runbooks/docker-memory.md", "Docker > Memory", "检查容器内存上限与进程泄漏，查看 OOM 事件。", 0.78)],
     ["内存", "OOM", "泄漏"]),
    ("如何确认容器网络是否可达？", "fixture/runbooks/docker-network.md",
     [("fixture/runbooks/docker-network.md", "Docker > Network", "检查网络驱动、端口映射与容器内 DNS 解析。", 0.81)],
     ["网络", "端口", "DNS"]),
    ("数据卷挂载权限报错怎么解决？", "fixture/runbooks/docker-volume.md",
     [("fixture/runbooks/docker-volume.md", "Docker > Volume", "确认宿主目录属主与容器内用户 UID 一致。", 0.76)],
     ["数据卷", "权限", "UID"]),
    ("容器健康检查持续失败怎么办？", "fixture/runbooks/docker-healthcheck.md",
     [("fixture/runbooks/docker-healthcheck.md", "Docker > Healthcheck", "核对探针命令、超时与启动宽限期设置。", 0.79)],
     ["健康检查", "探针", "超时"]),
    ("如何限制容器 CPU 使用？", "fixture/runbooks/docker-cpu.md",
     [("fixture/runbooks/docker-cpu.md", "Docker > CPU", "设置 CPU 配额与权重，并观察限流事件。", 0.75)],
     ["CPU", "配额", "限流"]),
    ("容器日志过大如何治理？", "fixture/runbooks/docker-logging.md",
     [("fixture/runbooks/docker-logging.md", "Docker > Logging", "配置日志驱动轮转与单文件大小上限。", 0.77)],
     ["日志", "轮转", "驱动"]),
    ("compose 编排启动顺序出错怎么办？", "fixture/runbooks/docker-compose.md",
     [("fixture/runbooks/docker-compose.md", "Docker > Compose", "使用依赖与健康检查控制启动顺序，避免竞态。", 0.80)],
     ["compose", "依赖", "启动"]),
    ("如何安全地更新运行中的容器？", "fixture/runbooks/docker-update.md",
     [("fixture/runbooks/docker-update.md", "Docker > Update", "先拉取新镜像并做健康验证，再滚动替换并保留回滚点。", 0.82)],
     ["更新", "镜像", "回滚"]),
]

ESXI = [
    ("ESXi 主机 datastore 空间不足时先检查什么？", "fixture/runbooks/esxi-datastore.md",
     [("fixture/runbooks/esxi-datastore.md", "Storage > Free space", "先查看 datastore 剩余空间与快照占用，再评估清理或扩容。", 0.86)],
     ["datastore", "存储", "快照"]),
    ("ESXi 虚拟机无法开机怎么办？", "fixture/runbooks/esxi-vm-poweron.md",
     [("fixture/runbooks/esxi-vm-poweron.md", "VM > Power On", "检查虚拟机文件完整性、资源预留与宿主主机状态。", 0.80)],
     ["虚拟机", "开机", "资源"]),
    ("如何确认 ESXi 宿主机硬件告警？", "fixture/runbooks/esxi-hardware.md",
     [("fixture/runbooks/esxi-hardware.md", "Hardware > Alerts", "查看传感器与 IPMI 事件，定位风扇、电源或磁盘告警。", 0.78)],
     ["硬件", "告警", "传感器"]),
    ("ESXi 管理网络失联如何恢复？", "fixture/runbooks/esxi-mgmt-network.md",
     [("fixture/runbooks/esxi-mgmt-network.md", "Network > Mgmt", "确认管理口链路与 vSwitch 上行，必要时用 DCUI 恢复。", 0.79)],
     ["管理网络", "vSwitch", "DCUI"]),
    ("快照占用过多空间怎么处理？", "fixture/runbooks/esxi-snapshots.md",
     [("fixture/runbooks/esxi-snapshots.md", "Storage > Snapshots", "评估快照链深度，在维护窗口合并或删除过期快照。", 0.84)],
     ["快照", "合并", "存储"]),
    ("ESXi 主机 CPU 就绪时间偏高怎么办？", "fixture/runbooks/esxi-ready-time.md",
     [("fixture/runbooks/esxi-ready-time.md", "Performance > Ready", "检查 CPU 超分比与宿主机负载，调整资源分配。", 0.77)],
     ["CPU", "就绪", "超分"]),
    ("如何检查 ESXi 的 NTP 时间同步？", "fixture/runbooks/esxi-ntp.md",
     [("fixture/runbooks/esxi-ntp.md", "System > Time", "确认 NTP 服务器可达并核对主机时间偏移。", 0.75)],
     ["NTP", "时间", "同步"]),
    ("ESXi 证书过期有什么影响？", "fixture/runbooks/esxi-certificate.md",
     [("fixture/runbooks/esxi-certificate.md", "Security > Certificates", "过期会导致管理界面与 API 告警，需按流程续期。", 0.76)],
     ["证书", "过期", "API"]),
    ("虚拟机迁移失败如何排查？", "fixture/runbooks/esxi-migration.md",
     [("fixture/runbooks/esxi-migration.md", "VM > Migration", "检查共享存储、网络兼容性与目标主机资源。", 0.81)],
     ["迁移", "存储", "兼容性"]),
    ("如何查看 ESXi 的磁盘 SMART 健康？", "fixture/runbooks/esxi-smart.md",
     [("fixture/runbooks/esxi-smart.md", "Storage > SMART", "读取磁盘 SMART 属性并关注重分配扇区计数。", 0.78)],
     ["SMART", "磁盘", "扇区"]),
]


def _rows(items):
    return [
        {"source_path": source, "heading_path": heading, "content": content, "similarity": similarity}
        for source, heading, content, similarity in items
    ]


def build() -> list[dict]:
    records: list[dict] = []
    for category, prefix, groups in (
        ("network", "NET", NETWORK),
        ("docker", "DOC", DOCKER),
        ("esxi", "ESX", ESXI),
    ):
        for index, (question, source, items, tokens) in enumerate(groups, start=1):
            records.append(
                {
                    "schema_version": "1",
                    "case_id": f"W17-{prefix}-{index:03d}",
                    "category": category,
                    "question": question,
                    "fixture": {
                        "rag_rows": _rows(items),
                        "mcp_health_data": "default-mock",
                    },
                    "expected": {
                        "retrieval": {"min_rows": 1, "required_source_path": source},
                        "mcp_contract": {
                            "tool_sequence": ["ping", "get_health_status"],
                            "all_arguments_empty": True,
                            "adapter_mode": "mock",
                            "read_only": True,
                        },
                        "answer": {
                            "must_include_any": tokens,
                            "must_not_include": ["OPENWRT", "real device"],
                            "provenance": True,
                        },
                    },
                    "tags": [category],
                    "notes": "sanitized fixture sample, no operational data",
                }
            )
    return records


def main():
    records = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    print(f"wrote {len(records)} records to {OUT}")


if __name__ == "__main__":
    main()
