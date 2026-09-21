"""MockAdapter providing sanitized, offline HomeLab data for development and testing."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional
from .models import BaseHomeLabAdapter, BasicMetrics, DeviceOrService, HealthStatus


class MockAdapter(BaseHomeLabAdapter):
    """Deterministic, read-only offline adapter with sanitized mock data."""

    def ping(self) -> Dict[str, object]:
        """Mock adapter is always reachable; no real network I/O occurs."""
        return {"reachable": True, "mode": "mock", "detail": "offline mock data, no network call performed"}

    def __init__(self) -> None:
        self._inventory: Dict[str, DeviceOrService] = {
            "router-openwrt": DeviceOrService(
                id="router-openwrt",
                name="Main Gateway Router",
                category="router",
                host="openwrt.lan",
                ip="192.168.1.1",
                port=80,
            ),
            "hypervisor-esxi": DeviceOrService(
                id="hypervisor-esxi",
                name="Primary ESXi Node",
                category="hypervisor",
                host="esxi01.lan",
                ip="192.168.1.2",
                port=443,
            ),
            "db-postgres": DeviceOrService(
                id="db-postgres",
                name="Production Postgres Cluster",
                category="database",
                host="db01.lan",
                ip="192.168.1.20",
                port=5432,
            ),
            "app-nginx": DeviceOrService(
                id="app-nginx",
                name="Edge Ingress Proxy",
                category="container",
                host="web01.lan",
                ip="192.168.1.10",
                port=80,
            ),
            "app-transmission": DeviceOrService(
                id="app-transmission",
                name="Torrent Download Service",
                category="storage",
                host="nas01.lan",
                ip="192.168.1.30",
                port=9091,
            ),
        }

        self._health: Dict[str, HealthStatus] = {
            "router-openwrt": HealthStatus(
                id="router-openwrt",
                name="Main Gateway Router",
                status="healthy",
                latency_ms=1.2,
                last_check_timestamp="2026-09-21T15:30:00Z",
                details="WAN connection stable, 0% packet loss",
            ),
            "hypervisor-esxi": HealthStatus(
                id="hypervisor-esxi",
                name="Primary ESXi Node",
                status="degraded",
                latency_ms=15.4,
                last_check_timestamp="2026-09-21T15:30:00Z",
                details="Datastore free space low (<10%), fans at high RPM",
            ),
            "db-postgres": HealthStatus(
                id="db-postgres",
                name="Production Postgres Cluster",
                status="healthy",
                latency_ms=3.1,
                last_check_timestamp="2026-09-21T15:30:00Z",
                details="Active connections 18/100, replication lag 0s",
            ),
            "app-nginx": HealthStatus(
                id="app-nginx",
                name="Edge Ingress Proxy",
                status="healthy",
                latency_ms=0.8,
                last_check_timestamp="2026-09-21T15:30:00Z",
                details="Upstream response 200 OK",
            ),
            "app-transmission": HealthStatus(
                id="app-transmission",
                name="Torrent Download Service",
                status="healthy",
                latency_ms=4.2,
                last_check_timestamp="2026-09-21T15:30:00Z",
                details="3 active torrent downloads, peer bandwidth normal",
            ),
        }

        self._metrics: Dict[str, BasicMetrics] = {
            "router-openwrt": BasicMetrics(
                id="router-openwrt",
                name="Main Gateway Router",
                cpu_percent=12.5,
                memory_percent=42.0,
                network_rx_mbps=85.4,
                network_tx_mbps=14.2,
            ),
            "hypervisor-esxi": BasicMetrics(
                id="hypervisor-esxi",
                name="Primary ESXi Node",
                cpu_percent=68.2,
                memory_percent=81.0,
                disk_percent=92.4,
                extra_stats={"running_vms": 6, "esxi_version": "8.0u2"},
            ),
            "db-postgres": BasicMetrics(
                id="db-postgres",
                name="Production Postgres Cluster",
                cpu_percent=45.0,
                memory_percent=74.5,
                disk_percent=55.0,
                extra_stats={"active_connections": 18, "transactions_per_sec": 142},
            ),
            "app-nginx": BasicMetrics(
                id="app-nginx",
                name="Edge Ingress Proxy",
                cpu_percent=8.0,
                memory_percent=22.0,
                network_rx_mbps=110.0,
                network_tx_mbps=95.0,
            ),
            "app-transmission": BasicMetrics(
                id="app-transmission",
                name="Torrent Download Service",
                cpu_percent=15.0,
                memory_percent=35.0,
                disk_percent=78.2,
                extra_stats={"active_torrents": 3, "download_speed_kbps": 4820},
            ),
        }

    def list_inventory(self, category_filter: Optional[str] = None) -> List[DeviceOrService]:
        items = list(self._inventory.values())
        if category_filter:
            items = [item for item in items if item.category.lower() == category_filter.lower()]
        return items

    def get_health(self, target_id: Optional[str] = None) -> List[HealthStatus]:
        if target_id:
            h = self._health.get(target_id)
            return [h] if h else []
        return list(self._health.values())

    def get_metrics(self, target_id: str) -> BasicMetrics:
        metrics = self._metrics.get(target_id)
        if not metrics:
            return BasicMetrics(
                id=target_id,
                name="Unknown Target",
                extra_stats={"error": f"No metrics found for target '{target_id}'"},
            )
        return metrics
