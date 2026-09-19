"""数据模型：Pydantic 模型 + dataclass + StrEnum。

为什么同时出现 Pydantic 和 dataclass？
- **Pydantic** 用于“边界”：从 JSON / 用户输入 / LLM 输出进入系统时，做运行时校验与
  类型强制转换。类比 C# 里带 DataAnnotations 的 DTO 或 FluentValidation。
- **dataclass** 用于“内部值对象”：不校验外部数据、只求轻量与不可变，例如统计摘要。
  类比 C# 的 ``record``。

注意：Python 的 type hints 默认只是给静态检查器（mypy/pyright）看的，运行时不强制；
Pydantic 才把 hints 变成真正的运行时校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "Hostname",
    "HostKind",
    "HealthStatus",
    "Host",
    "Inventory",
    "CheckResult",
    "CheckSummary",
]

# 复用式类型别名：把一个受限字符串类型抽出来，供多个字段使用。
# 等价于 C# 的 value object / 自定义 struct。
Hostname = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
        description="RFC1123 风格的主机名",
    ),
]


class HostKind(StrEnum):
    """主机类型。``StrEnum`` 让成员本身就是 str，序列化后是普通字符串。"""

    ESXI = "esxi"
    DOCKER = "docker"
    OPENWRT = "openwrt"
    HOST = "host"


class HealthStatus(StrEnum):
    """健康状态。"""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class Host(BaseModel):
    """清单中的一台主机（外部数据边界 → 需要校验）。"""

    # frozen=True: 实例不可变；extra="forbid": 拒绝未知字段，避免配置拼写错误被静默忽略。
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Hostname
    kind: HostKind
    address: str = Field(min_length=1, description="IP 或 DNS 名称")
    tags: list[str] = Field(default_factory=list)
    expected_latency_ms: int = Field(default=100, ge=1, le=10_000)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        """把标签统一为小写、去空格、去重并排序，保证输出的确定性。"""
        cleaned = {tag.strip().lower() for tag in value if tag.strip()}
        return sorted(cleaned)


class Inventory(BaseModel):
    """整份主机清单。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hosts: list[Host] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_names(self) -> Inventory:
        """跨字段校验：主机名必须唯一。"""
        names = [host.name for host in self.hosts]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate host name(s): {', '.join(duplicates)}")
        return self

    def find(self, name: str) -> Host | None:
        """按名称查找主机；找不到返回 ``None``（把“未找到”交给调用方决定如何报错）。"""
        return next((host for host in self.hosts if host.name == name), None)


class CheckResult(BaseModel):
    """单台主机的检查结果。"""

    model_config = ConfigDict(frozen=True)

    host: Host
    status: HealthStatus
    latency_ms: int = Field(ge=0)
    message: str = ""


@dataclass(frozen=True, slots=True)
class CheckSummary:
    """多台主机的汇总统计（内部值对象 → 用 dataclass 更轻）。

    这是“只在自己的代码内部传递、不需要外部校验”的典型场景。
    """

    total: int
    up: int
    degraded: int
    down: int
    unknown: int

    @property
    def healthy(self) -> bool:
        """没有任何 DOWN / UNKNOWN 时视为整体健康。"""
        return self.down == 0 and self.unknown == 0

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典。"""
        return {
            "total": self.total,
            "up": self.up,
            "degraded": self.degraded,
            "down": self.down,
            "unknown": self.unknown,
            "healthy": self.healthy,
        }
