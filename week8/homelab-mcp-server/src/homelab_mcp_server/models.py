"""Data models and abstract interface for HomeLab data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
    """Validated JSON configuration for RealAdapter."""
    base_url: str = Field(..., description="Target HomeLab base URL, e.g. http://192.168.1.100:8080")
    auth_token: Optional[str] = Field(None, description="Optional Bearer authentication token")
    timeout_seconds: float = Field(5.0, ge=0.5, le=60.0, description="HTTP connection timeout in seconds")


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
