"""Data models and abstract interface for HomeLab data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class DeviceOrService(BaseModel):
    id: str
    name: str
    category: str  # e.g., "hypervisor", "database", "storage", "router", "container"
    host: str
    ip: Optional[str] = None
    port: Optional[int] = None


class HealthStatus(BaseModel):
    id: str
    name: str
    status: str  # "healthy", "degraded", "down", "unknown"
    latency_ms: Optional[float] = None
    last_check_timestamp: str
    details: str


class BasicMetrics(BaseModel):
    id: str
    name: str
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_percent: Optional[float] = None
    network_rx_mbps: Optional[float] = None
    network_tx_mbps: Optional[float] = None
    extra_stats: Dict[str, Any] = Field(default_factory=dict)


class RealAdapterConfig(BaseModel):
    """Validated JSON configuration for RealAdapter.

    Path templates are configurable because real HomeLab devices (e.g. OpenWrt)
    do not natively expose a unified REST API like '/api/v1/health/{target_id}'.
    OpenWrt's native status interface is ubus-over-HTTP, which requires
    session-authenticated POST calls and is therefore incompatible with this
    project's strict read-only GET-only security boundary. Point these
    templates at whatever read-only GET endpoint you actually have in front of
    your devices (e.g. a small exporter/gateway script, Prometheus-style
    metrics endpoint, or reverse proxy translating GET -> ubus internally).
    """
    base_url: str = Field(..., description="Target HomeLab base URL, e.g. http://192.168.1.100:8080")
    auth_token: Optional[str] = Field(None, description="Optional Bearer authentication token")
    timeout_seconds: float = Field(5.0, ge=0.5, le=60.0, description="HTTP connection timeout in seconds")
    inventory_path: str = Field(
        "/api/v1/inventory",
        description="GET path returning the device/service inventory list",
    )
    health_list_path: str = Field(
        "/api/v1/health",
        description="GET path returning health status for all targets",
    )
    health_path_template: str = Field(
        "/api/v1/health/{target_id}",
        description="GET path template (must contain '{target_id}') for a single target's health status",
    )
    metrics_path_template: str = Field(
        "/api/v1/metrics/{target_id}",
        description="GET path template (must contain '{target_id}') for a single target's metrics",
    )

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Accept a bare host/IP (e.g. '192.168.1.1' or '192.168.1.1:8080') and
        auto-prepend 'http://' if no scheme is present, so httpx does not raise
        UnsupportedProtocol on a plain IP address."""
        value = value.strip()
        if not value:
            raise ValueError("base_url cannot be empty")
        if "://" not in value:
            value = f"http://{value}"
        return value

    @field_validator("health_path_template", "metrics_path_template")
    @classmethod
    def require_target_id_placeholder(cls, value: str) -> str:
        if "{target_id}" not in value:
            raise ValueError("path template must contain the '{target_id}' placeholder")
        return value


class BaseHomeLabAdapter(ABC):
    """Abstract Base Class defining the read-only contract for HomeLab operations."""

    @abstractmethod
    def ping(self) -> Dict[str, Any]:
        """Check adapter-level connectivity/liveness. Must remain read-only (no side effects)."""
        pass

    @abstractmethod
    def list_inventory(self, category_filter: Optional[str] = None) -> List[DeviceOrService]:
        """List all discovered devices and services."""
        pass

    @abstractmethod
    def get_health(self, target_id: Optional[str] = None) -> List[HealthStatus]:
        """Get health status for a specific device/service or all targets."""
        pass

    @abstractmethod
    def get_metrics(self, target_id: str) -> BasicMetrics:
        """Get current basic resource metrics for a target device."""
        pass
