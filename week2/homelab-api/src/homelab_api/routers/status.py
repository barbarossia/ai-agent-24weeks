"""分类状态路由：``GET /docker/status`` 与 ``GET /network/status``。

对应 Week 2 计划实战要求的两个聚合端点。
它们把"筛选主机 → 并发检查 → 汇总"串成一条稳定的读路径，
且与具体数据来源解耦（清单来自 Depends，未来可换成真实 CMDB）。
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter

from ai_agent_lab.models import CheckResult, Host, HostKind, Inventory
from ai_agent_lab.service import summarize

from ..deps import InventoryDep, ProbeDep
from ..schemas import CheckResultOut, StatusResponse, SummaryOut
from ..service_async import AsyncProbe, check_all_async

__all__ = ["router"]

router = APIRouter(tags=["status"])


def _docker_hosts(inventory: Inventory) -> list[Host]:
    """Docker 主机：kind == docker。"""
    return [host for host in inventory.hosts if host.kind == HostKind.DOCKER]


def _network_hosts(inventory: Inventory) -> list[Host]:
    """网络设备：kind == openwrt，或标签里带 network / gateway。

    刻意展示"多维筛选"：真实环境里设备分类未必只靠单一字段。
    """
    return [
        host
        for host in inventory.hosts
        if host.kind == HostKind.OPENWRT
        or "network" in host.tags
        or "gateway" in host.tags
    ]


async def _status_for(
    kind: str,
    hosts: Sequence[Host],
    probe: AsyncProbe,
) -> StatusResponse:
    results: list[CheckResult] = await check_all_async(hosts, probe=probe)
    return StatusResponse(
        kind=kind,
        results=[CheckResultOut.from_domain(result) for result in results],
        summary=SummaryOut.from_domain(summarize(results)),
    )


@router.get(
    "/docker/status",
    response_model=StatusResponse,
    summary="Docker 主机状态",
    description="筛选所有 docker 类型主机并并发检查；无 docker 主机时返回空列表且 healthy=true。",
)
async def docker_status(
    inventory: InventoryDep,
    probe: ProbeDep,
) -> StatusResponse:
    return await _status_for("docker", _docker_hosts(inventory), probe)


@router.get(
    "/network/status",
    response_model=StatusResponse,
    summary="网络设备状态",
    description="筛选 openwrt / network / gateway 主机并并发检查。",
)
async def network_status(
    inventory: InventoryDep,
    probe: ProbeDep,
) -> StatusResponse:
    return await _status_for("network", _network_hosts(inventory), probe)
