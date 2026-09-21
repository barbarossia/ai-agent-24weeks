"""RealAdapter providing strictly read-only HTTP/REST integration for real HomeLab.

Configuration:
- Environment variable `HOMELAB_BASE_URL` (e.g., http://homelab-api.local:8080)
- Environment variable `HOMELAB_AUTH_TOKEN` (Bearer token or API key)
- Environment variable `HOMELAB_HTTP_TIMEOUT` (seconds, default 5.0)

Safety Constraints:
- Only performs HTTP GET requests.
- Mutating methods (POST/PUT/DELETE/PATCH) are strictly prohibited.
- Does not expose or store credentials in code or logs.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import httpx
from .models import BaseHomeLabAdapter, BasicMetrics, DeviceOrService, HealthStatus


class RealAdapter(BaseHomeLabAdapter):
    """Safe, read-only HTTP adapter connecting to external HomeLab REST endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("HOMELAB_BASE_URL", "")).rstrip("/")
        self.auth_token = auth_token or os.getenv("HOMELAB_AUTH_TOKEN", "")
        self.timeout = timeout or float(os.getenv("HOMELAB_HTTP_TIMEOUT", "5.0"))

        if not self.base_url:
            raise ValueError(
                "HOMELAB_BASE_URL must be configured when using RealAdapter. "
                "Set the environment variable or pass base_url explicitly."
            )

        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False,
        )

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a strictly read-only GET request."""
        try:
            resp = self._client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {"error": f"HomeLab HTTP GET failed: {exc.__class__.__name__}: {str(exc)}"}

    def list_inventory(self, category_filter: Optional[str] = None) -> List[DeviceOrService]:
        params = {"category": category_filter} if category_filter else None
        data = self._get("/api/v1/inventory", params=params)
        if isinstance(data, list):
            return [DeviceOrService.model_validate(item) for item in data]
        if isinstance(data, dict) and "items" in data:
            return [DeviceOrService.model_validate(item) for item in data["items"]]
        return []

    def get_health(self, target_id: Optional[str] = None) -> List[HealthStatus]:
        path = f"/api/v1/health/{target_id}" if target_id else "/api/v1/health"
        data = self._get(path)
        if isinstance(data, list):
            return [HealthStatus.model_validate(item) for item in data]
        if isinstance(data, dict):
            if "status" in data:
                return [HealthStatus.model_validate(data)]
            if "items" in data:
                return [HealthStatus.model_validate(item) for item in data["items"]]
        return []

    def get_metrics(self, target_id: str) -> BasicMetrics:
        data = self._get(f"/api/v1/metrics/{target_id}")
        if isinstance(data, dict) and "cpu_percent" in data:
            return BasicMetrics.model_validate(data)
        return BasicMetrics(
            id=target_id,
            name=f"Device-{target_id}",
            extra_stats={"response": data},
        )

    def close(self) -> None:
        self._client.close()
