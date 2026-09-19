"""统一错误契约：把领域异常映射为稳定的 JSON 错误响应。

Week 1 的目标是"异常树 + 退出码"；Week 2 的目标是"异常树 + HTTP 状态码 + JSON 外壳"。
分层不变，只是最外层的消费者从 shell 换成了 HTTP 客户端：

| 领域异常            | HTTP | error.code       |
|---------------------|------|------------------|
| HostNotFoundError   | 404  | host_not_found   |
| InventoryError      | 422  | inventory_error  |
| CheckFailedError    | 503  | check_failed     |
| RequestValidationError | 422 | validation_error |
| 其他领域异常基类    | 500  | internal_error   |

统一响应外壳：``{"error": {"code": "...", "message": "...", "hostname": ...}}``。
客户端只需读 ``error.code`` 做分支，不用解析人类可读的 message。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai_agent_lab.errors import (
    AiAgentLabError,
    CheckFailedError,
    HostNotFoundError,
    InventoryError,
)

from .schemas import ErrorResponse

__all__ = ["install_exception_handlers"]


def _error_payload(
    code: str,
    message: str,
    hostname: str | None = None,
) -> dict[str, object]:
    """构造统一错误外壳（用 schema 保证字段与文档一致）。"""
    body = ErrorResponse.model_validate(
        {"error": {"code": code, "message": message, "hostname": hostname}}
    )
    return body.model_dump(mode="json")


def install_exception_handlers(app: FastAPI) -> None:
    """在 app 上注册领域异常 → HTTP 响应的处理器。

    设计要点：处理器与路由解耦。任何一个 handler 抛领域异常，
    都会自动得到一致的状态码与 JSON 结构，不用在每处 try/except。
    """

    @app.exception_handler(HostNotFoundError)
    async def _handle_host_not_found(
        _request: Request, exc: HostNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error_payload("host_not_found", str(exc), exc.hostname),
        )

    @app.exception_handler(InventoryError)
    async def _handle_inventory_error(
        _request: Request, exc: InventoryError
    ) -> JSONResponse:
        # 清单本身不合法属于"输入数据错误"，用 422 而非 500。
        return JSONResponse(
            status_code=422,
            content=_error_payload("inventory_error", str(exc)),
        )

    @app.exception_handler(CheckFailedError)
    async def _handle_check_failed(
        _request: Request, exc: CheckFailedError
    ) -> JSONResponse:
        # 探针失败是"下游依赖不可用"，属于暂时性故障 → 503（可重试语义）。
        return JSONResponse(
            status_code=503,
            content=_error_payload(
                "check_failed",
                str(exc),
                exc.hostname,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """覆盖 FastAPI 默认的 422 格式，统一进 ``{"error": {...}}`` 外壳。

        默认的 detail 是数组；这里压成一句人类可读的 message，
        客户端仍可通过 code == "validation_error" 做统一处理。
        """
        parts: list[str] = []
        for err in exc.errors()[:5]:  # 最多展示 5 条，避免响应过长
            location = ".".join(str(item) for item in err.get("loc", ()))
            parts.append(f"{location}: {err.get('msg', 'invalid value')}")
        message = "; ".join(parts) or "request validation failed"
        return JSONResponse(
            status_code=422,
            content=_error_payload("validation_error", message),
        )

    @app.exception_handler(AiAgentLabError)
    async def _handle_domain_error(
        _request: Request, exc: AiAgentLabError
    ) -> JSONResponse:
        # 兜底：任何未细分的领域异常都不应变成 500 traceback 泄露内部细节。
        return JSONResponse(
            status_code=500,
            content=_error_payload("internal_error", str(exc)),
        )
