"""API 边界的 Pydantic 模型（请求 / 响应 schema）。

为什么不直接在路由里返回 Week 1 的领域模型（``ai_agent_lab.models.Host``）？
- **领域模型 ≠ API 契约**。领域模型随内部重构而变，API 契约要对客户端保持稳定。
- 边界职责不同：领域模型可能含内部字段；API schema 只暴露允许公开的部分。
- 这层 domain → schema 映射本身就是一道防线：不会不小心泄露内部结构。

对照 C#：这等价于 Entity / DTO(ViewModel) 的分离。
Pydantic 在这里承担两个职责：
1. **响应序列化**：把 Python 对象转成 JSON；
2. **请求校验**：把外部 JSON 转成可信的强类型对象（失败即 422）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_agent_lab.models import CheckResult, CheckSummary, HealthStatus, Host

__all__ = [
    "HostOut",
    "CheckResultOut",
    "SummaryOut",
    "HealthResponse",
    "CheckRequest",
    "CheckResponse",
    "StatusResponse",
    "ErrorDetail",
    "ErrorResponse",
]


class HostOut(BaseModel):
    """单台主机的公开表示。"""

    # frozen=True：响应对象不可变，避免 handler 之间互相篡改。
    model_config = ConfigDict(frozen=True)

    name: str
    kind: str
    address: str
    tags: list[str]
    expected_latency_ms: int

    @classmethod
    def from_domain(cls, host: Host) -> HostOut:
        """领域对象 → API schema 的显式映射。"""
        return cls(
            name=host.name,
            # HostKind 是 StrEnum，.value 才是普通字符串；不依赖隐式转换更清晰。
            kind=host.kind.value,
            address=host.address,
            tags=list(host.tags),
            expected_latency_ms=host.expected_latency_ms,
        )


class CheckResultOut(BaseModel):
    """一次检查的结果。"""

    model_config = ConfigDict(frozen=True)

    host: HostOut
    status: HealthStatus
    latency_ms: int
    message: str

    @classmethod
    def from_domain(cls, result: CheckResult) -> CheckResultOut:
        return cls(
            host=HostOut.from_domain(result.host),
            status=result.status,
            latency_ms=result.latency_ms,
            message=result.message,
        )


class SummaryOut(BaseModel):
    """多个结果的汇总统计。"""

    model_config = ConfigDict(frozen=True)

    total: int
    up: int
    degraded: int
    down: int
    unknown: int
    healthy: bool

    @classmethod
    def from_domain(cls, summary: CheckSummary) -> SummaryOut:
        return cls(
            total=summary.total,
            up=summary.up,
            degraded=summary.degraded,
            down=summary.down,
            unknown=summary.unknown,
            healthy=summary.healthy,
        )


class HealthResponse(BaseModel):
    """``GET /health`` 的响应：存活探针。"""

    model_config = ConfigDict(frozen=True)

    # Literal["ok"]：响应里 status 只允许 "ok"，写错在开发期就会被 Pydantic 拦住。
    status: Literal["ok"]
    service: str
    version: str
    week: int


class CheckRequest(BaseModel):
    """``POST /hosts/check`` 的请求体 —— 演示 Pydantic **请求**模型与校验。

    这是本周唯一带请求体的接口：GET 没有 body，用 POST 才能看到
    "外部 JSON → 校验 → 强类型对象" 的完整链路，以及校验失败时的 422。
    """

    # extra="forbid"：客户端多传字段会直接 422，而不是被静默忽略（防拼写错误）。
    model_config = ConfigDict(frozen=True, extra="forbid")

    names: list[str] = Field(
        min_length=1,
        description="要检查的主机名列表；至少 1 个，未知主机返回 404。",
    )
    concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description="并发上限（asyncio.Semaphore 的容量）。",
    )
    timeout_ms: int = Field(
        default=2_000,
        ge=100,
        le=30_000,
        description="预留的超时预算（毫秒），当前实现仅做范围校验。",
    )


class CheckResponse(BaseModel):
    """``POST /hosts/check`` 的响应。"""

    model_config = ConfigDict(frozen=True)

    results: list[CheckResultOut]
    summary: SummaryOut


class StatusResponse(BaseModel):
    """按类别返回状态（docker / network）。"""

    model_config = ConfigDict(frozen=True)

    kind: str
    results: list[CheckResultOut]
    summary: SummaryOut


class ErrorDetail(BaseModel):
    """错误详情：结构化字段，客户端无需解析字符串。"""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    hostname: str | None = None


class ErrorResponse(BaseModel):
    """全站统一的错误响应外壳：``{"error": {...}}``。"""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail
