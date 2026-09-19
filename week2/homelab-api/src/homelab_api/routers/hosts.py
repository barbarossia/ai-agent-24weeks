"""主机相关路由：列清单、查单台、批量检查。

注意路由顺序：``POST /hosts/check`` 与 ``GET /hosts/{name}`` 方法不同，
不会冲突；但若将来把 check 改成 GET，就必须把它声明在 ``/{name}`` **之前**，
否则 "check" 会被当成主机名。这是一个经典的 FastAPI 踩坑点。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ai_agent_lab.errors import HostNotFoundError
from ai_agent_lab.service import summarize

from ..deps import InventoryDep, ProbeDep
from ..schemas import (
    CheckRequest,
    CheckResponse,
    CheckResultOut,
    HostOut,
    SummaryOut,
)
from ..service_async import check_all_async

__all__ = ["router"]

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.get(
    "",
    response_model=list[HostOut],
    summary="列出全部主机",
    description="返回清单中的所有主机（不执行探针，纯读操作）。",
)
async def list_hosts(inventory: InventoryDep) -> list[HostOut]:
    return [HostOut.from_domain(host) for host in inventory.hosts]


@router.get(
    "/{name}",
    response_model=HostOut,
    summary="查询单台主机",
    description="按主机名查询；不存在时返回 404 与 ``error.code=host_not_found``。",
)
async def get_host(
    inventory: InventoryDep,
    name: Annotated[str, Path(description="主机名，例如 openwrt-01")],
) -> HostOut:
    host = inventory.find(name)
    if host is None:
        # 抛出领域异常；由全局 exception_handler 统一映射为 404 JSON。
        raise HostNotFoundError(name)
    return HostOut.from_domain(host)


@router.post(
    "/check",
    response_model=CheckResponse,
    summary="批量检查指定主机（并发）",
    description=(
        "请求体 names 至少 1 个；concurrency 限制同时在飞的探针数。"
        "任一主机名不存在返回 404；请求体不合法返回 422。"
    ),
)
async def check_hosts(
    payload: CheckRequest,
    inventory: InventoryDep,
    probe: ProbeDep,
) -> CheckResponse:
    hosts = []
    for name in payload.names:
        host = inventory.find(name)
        if host is None:
            raise HostNotFoundError(name)
        hosts.append(host)

    results = await check_all_async(
        hosts,
        probe=probe,
        concurrency=payload.concurrency,
    )
    return CheckResponse(
        results=[CheckResultOut.from_domain(result) for result in results],
        summary=SummaryOut.from_domain(summarize(results)),
    )
