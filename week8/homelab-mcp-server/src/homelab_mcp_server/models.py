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


class OpenWrtAdapterConfig(BaseModel):
    """Validated JSON configuration for OpenWrtUbusAdapter.

    Targets OpenWrt's real, native management interface: ubus-over-HTTP
    (the '/ubus' JSON-RPC 2.0 endpoint used by LuCI itself), not a fictional
    REST API. Requires a session login (ubus 'session'/'login' call) before
    any other ubus call can be made.
    """
    base_url: str = Field(..., description="OpenWrt base URL, e.g. http://192.168.1.1")
    username: str = Field("root", description="OpenWrt/LuCI username for ubus session login")
    password: str = Field(..., description="OpenWrt/LuCI password for ubus session login")
    timeout_seconds: float = Field(5.0, ge=0.5, le=60.0, description="HTTP connection timeout in seconds")

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Accept a bare host/IP (e.g. '192.168.1.1') and auto-prepend 'http://'
        if no scheme is present, so httpx does not raise UnsupportedProtocol."""
        value = value.strip()
        if not value:
            raise ValueError("base_url cannot be empty")
        if "://" not in value:
            value = f"http://{value}"
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
