"""共享测试夹具。

核心思想：把**时间**与**等待**这两个不确定源都换成可注入的假实现：
- ``RecordingSleeper``：记录退避延迟但不真的等待 → 测试秒回且能断言延迟序列；
- ``FakeClock``：每次读取前进固定步长 → 延迟统计确定，不依赖墙钟。

再加上 ``ScriptedProvider``，坏路径（429/5xx/坏 JSON/超时）都能精确复现。
"""

from __future__ import annotations

import pytest

from llm_api_lab.client import RetryPolicy
from llm_api_lab.messages import Conversation, Message, Role
from llm_api_lab.providers import MockProvider

SAMPLE_QUESTION = "NAS 磁盘快满了，服务很慢"


class RecordingSleeper:
    """假的 sleep：只记录请求的秒数，不真的等待。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class FakeClock:
    """假的单调时钟：每次调用前进 ``step`` 秒。"""

    def __init__(self, step: float = 0.25) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        self._now += self._step
        return self._now


@pytest.fixture
def question() -> str:
    return SAMPLE_QUESTION


@pytest.fixture
def conversation(question: str) -> Conversation:
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content="你是 HomeLab 运维助手。"),
            Message(role=Role.USER, content=question),
        ]
    )


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def fast_retry() -> RetryPolicy:
    # 确定性、无 jitter、毫秒级基数的重试策略。
    return RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=1.0)


@pytest.fixture
def sleeper() -> RecordingSleeper:
    return RecordingSleeper()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(step=0.25)
