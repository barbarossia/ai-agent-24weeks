"""FastAPI 依赖注入（``Depends``）提供者。

``Depends`` 的价值：路由函数只**声明**"我需要什么"，由框架负责构造与注入。
- 复用：清单/探针/配置只写一次，多处路由共享；
- 可测：测试里用 ``app.dependency_overrides`` 换成假实现，
  不读文件、不发网络、不等待 —— 这正是 Week 1"参数注入 probe"思想的框架化版本；
- 显式：依赖关系写在函数签名里，一眼可见（不像全局单例那样隐蔽）。

对照 C#：``Depends`` ≈ 构造函数注入 + ``IServiceProvider``，
但 FastAPI 是"函数参数级"注入，更轻量。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from ai_agent_lab.models import Inventory
from ai_agent_lab.service import default_inventory

from . import __version__
from .service_async import AsyncProbe, async_probe

__all__ = [
    "AppSettings",
    "get_settings",
    "get_inventory",
    "get_probe",
    "SettingsDep",
    "InventoryDep",
    "ProbeDep",
]


class AppSettings(BaseModel):
    """应用配置（此处为常量，扩展点：改成读环境变量 / ``pydantic-settings``）。"""

    model_config = ConfigDict(frozen=True)

    service_name: str = "homelab-api"
    version: str = __version__
    week: int = 2
    default_concurrency: int = 4


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """配置是进程内常量：用 ``lru_cache`` 保证只构造一次。

    *扩展点*：真实项目里这里可以 ``os.environ`` / ``pydantic-settings`` 读取，
    但**不要把凭据写进代码或日志**（本周不涉及任何密钥）。
    """
    return AppSettings()


def get_inventory() -> Inventory:
    """提供主机清单。默认用 Week 1 的内置示例清单，无需外部文件即可运行。

    *扩展点*：可改为按环境变量指向 JSON 文件（复用 ``load_inventory``）。
    测试可 override 成一个小清单，让断言稳定。
    """
    return default_inventory()


def get_probe() -> AsyncProbe:
    """提供异步探针。测试可 override 成固定延迟 / 抛异常的探针。"""
    return async_probe


# 复用式依赖别名：路由签名里写 ``InventoryDep`` 即可，少写样板、意图清晰。
SettingsDep = Annotated[AppSettings, Depends(get_settings)]
InventoryDep = Annotated[Inventory, Depends(get_inventory)]
ProbeDep = Annotated[AsyncProbe, Depends(get_probe)]
