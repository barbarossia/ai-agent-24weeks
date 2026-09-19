"""``GET /health`` —— 最小存活探针。

这类端点故意不依赖任何外部资源：它回答的是"进程还活着吗"，
而不是"依赖是否健康"。依赖健康用 /docker/status、/network/status 表达。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import SettingsDep
from ..schemas import HealthResponse

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="存活探针",
    description="返回服务名、版本与学习周次；不依赖任何下游资源。",
)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        week=settings.week,
    )
