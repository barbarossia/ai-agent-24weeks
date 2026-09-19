"""自定义异常层级。

设计要点（C# 对照）：
- Python 没有 checked exception，异常用于表达“调用方无法继续”的错误。
- 建立一棵以 ``AiAgentLabError`` 为根的异常树，调用方可以：
    * 捕获具体异常（``InventoryError``）做精细处理；
    * 或捕获基类统一兜底。
  这与 C# 中 ``catch (MyAppException ex)`` 的思路一致。
- 使用 ``raise ... from exc`` 保留原始异常链（类似 C# 的 InnerException）。
"""

from __future__ import annotations

__all__ = [
    "AiAgentLabError",
    "InventoryError",
    "HostNotFoundError",
    "CheckFailedError",
]


class AiAgentLabError(Exception):
    """本项目所有异常的基类（catch-all 兜底用）。"""


class InventoryError(AiAgentLabError):
    """清单文件缺失、无法解析，或数据结构不合法。"""


class HostNotFoundError(AiAgentLabError):
    """查询的主机名不在清单中。"""

    def __init__(self, hostname: str) -> None:
        super().__init__(f"host not found: {hostname!r}")
        # 保留结构化字段，便于上层程序化处理，而不是去解析字符串
        self.hostname = hostname


class CheckFailedError(AiAgentLabError):
    """执行健康检查时发生不可恢复错误（例如探针抛异常）。"""

    def __init__(self, hostname: str, reason: str) -> None:
        super().__init__(f"check failed for {hostname!r}: {reason}")
        self.hostname = hostname
        self.reason = reason
