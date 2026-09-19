"""示例 3：超时与重试 —— 只对**暂时性故障**退避重试。

运行：``uv run python examples/03_retry_and_errors.py``

演示三件事：
1. 429 限流：优先按服务端 ``Retry-After`` 等待；
2. 503：按指数退避等待；
3. 401 鉴权错误：**不可重试**，立即失败（重试只会浪费配额）。
"""

from __future__ import annotations

import asyncio

from llm_api_lab.client import LLMClient, RetryPolicy
from llm_api_lab.errors import LlmAuthError, LlmRateLimitError, LlmServerError
from llm_api_lab.messages import Conversation, Message, Role
from llm_api_lab.models import ModelConfig
from llm_api_lab.providers import Script, ScriptedProvider


def conversation(text: str) -> Conversation:
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content="你是 HomeLab 运维助手。"),
            Message(role=Role.USER, content=text),
        ]
    )


async def retryable_success() -> None:
    delays: list[float] = []

    async def sleeper(seconds: float) -> None:
        delays.append(seconds)  # 只记录，不真等待

    provider = ScriptedProvider(
        scripts=[
            Script(error=LlmRateLimitError("429", retry_after_s=0.3)),
            Script(error=LlmServerError(503, "upstream unavailable")),
            Script(text='{"category":"network","severity":"warning","action":"check_dns"}'),
        ]
    )
    client = LLMClient(
        provider,
        config=ModelConfig(model="mock-llm-v1"),
        retry=RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=1.0),
        sleeper=sleeper,
    )
    completion = await client.complete(conversation("DNS 延迟很高"))
    print(f"[retryable] attempts={completion.attempts} delays={delays}")
    print(f"[retryable] finish_reason={completion.finish_reason}")


async def non_retryable_failure() -> None:
    provider = ScriptedProvider(
        scripts=[
            Script(error=LlmAuthError(401, "invalid api key")),
            Script(text="this must never be reached"),
        ]
    )
    client = LLMClient(
        provider,
        config=ModelConfig(model="mock-llm-v1"),
        retry=RetryPolicy(max_attempts=3, base_delay_s=0.1),
    )
    try:
        await client.complete(conversation("hello"))
    except LlmAuthError as exc:
        print(f"[fatal]     {exc} -> attempts={len(provider.calls)} (no retry)")


async def main() -> int:
    await retryable_success()
    await non_retryable_failure()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
