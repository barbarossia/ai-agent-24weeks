"""应用工厂：``create_app()``。

为什么用工厂函数而不是模块级 ``app = FastAPI()``？
- **测试隔离**：每个测试 ``create_app()`` 得到干净实例，依赖覆盖互不污染；
- **可配置**：将来可传入不同 settings / 生命周期钩子；
- **生产兼容**：uvicorn 仍可用 ``homelab_api.main:app`` 指向工厂产物。

分层回顾（Week 1 → Week 2）：
``routers``（HTTP 语义） → ``deps``（装配） → ``service_async``（异步业务）
→ ``ai_agent_lab.service/models``（Week 1 领域层，被完整复用）。
HTTP 细节与业务逻辑依然互不认识。
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .deps import get_settings
from .errors import install_exception_handlers
from .routers import health, hosts, status
from . import events

__all__ = ["create_app", "app"]


def create_app() -> FastAPI:
    """构造并装配 FastAPI 应用。"""
    settings = get_settings()

    app = FastAPI(
        title="HomeLab API",
        version=__version__,
        description=(
            "Week 2 学习项目：用 async/await + FastAPI 把 Week 1 的 HomeLab "
            "主机检查逻辑暴露为 REST API，并演示 SSE / WebSocket 基础。"
        ),
    )

    # 错误契约（领域异常 → HTTP + JSON 外壳）在装配阶段一次性注册。
    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(hosts.router)
    app.include_router(status.router)
    app.include_router(events.router)

    @app.get("/", include_in_schema=False)
    async def index() -> dict[str, object]:
        """根路径给个入口提示；交互式文档在 /docs。"""
        return {
            "service": settings.service_name,
            "version": settings.version,
            "week": settings.week,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


# uvicorn 生产入口：uvicorn homelab_api.main:app
app = create_app()
