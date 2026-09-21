"""RealAdapter providing strictly read-only HTTP/REST integration for real HomeLab.

Configuration:
- JSON string via environment variable HOMELAB_CONFIG_JSON
- Path to JSON configuration file via HOMELAB_CONFIG_FILE
- Or by passing RealAdapterConfig directly to RealAdapter(config=...)

Safety Constraints:
- Only performs HTTP GET requests.
- Mutating methods (POST/PUT/DELETE/PATCH) are strictly prohibited.
- Does not expose or store credentials in code or logs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from .models import BaseHomeLabAdapter, BasicMetrics, DeviceOrService, HealthStatus, RealAdapterConfig


class RealAdapter(BaseHomeLabAdapter):
    """Safe, read-only HTTP adapter connecting to external HomeLab REST endpoints."""

    def __init__(
        self,
        config: Optional[RealAdapterConfig] = None,
        config_json: Optional[str] = None,
        config_file: Optional[str] = None,
    ) -> None:
        if config is not None:
            self.config = config
        elif config_json is not None:
            self.config = RealAdapterConfig.model_validate_json(config_json)
        elif config_file is not None:
            raw_text = Path(config_file).read_text(encoding="utf-8")
            self.config = RealAdapterConfig.model_validate_json(raw_text)
        elif "HOMELAB_CONFIG_JSON" in os.environ:
            self.config = RealAdapterConfig.model_validate_json(os.environ["HOMELAB_CONFIG_JSON"])
        elif "HOMELAB_CONFIG_FILE" in os.environ:
            raw_text = Path(os.environ["HOMELAB_CONFIG_FILE"]).read_text(encoding="utf-8")
            self.config = RealAdapterConfig.model_validate_json(raw_text)
        else:
            raise ValueError(
                "RealAdapter requires JSON-backed configuration. Provide RealAdapterConfig, "
                "or set HOMELAB_CONFIG_JSON or HOMELAB_CONFIG_FILE."
            )

        self.base_url = self.config.base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("RealAdapterConfig 'base_url' cannot be empty.")

        headers = {"Accept": "application/json"}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.config.timeout_seconds,
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
