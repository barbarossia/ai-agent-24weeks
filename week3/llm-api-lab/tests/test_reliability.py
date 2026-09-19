"""可靠性：超时、退避重试、不可重试错误、延迟与成本统计的测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from llm_api_lab.client import LLMClient, RetryPolicy
from llm_api_lab.errors import (
    LlmAuthError,
    LlmClientError,
    LlmRateLimitError,
    LlmServerError,
    LlmTimeoutError,
)
from llm_api_lab.messages import Conversation
from llm_api_lab.models import ModelConfig, Usage
from llm_api_lab.providers import Script, ScriptedProvider
from llm_api_lab.usage import ModelPricing

if TYPE_CHECKING:  # 仅用于类型标注；pytest 在运行时注入真实夹具对象
    from conftest import FakeClock, RecordingSleeper


async def test_retryable_errors_then_success(
    conversation: Conversation, fast_retry: RetryPolicy, sleeper: RecordingSleeper
) -> None:
    provider = ScriptedProvider(
        scripts=[
            Script(error=LlmRateLimitError("429", retry_after_s=0.5)),
            Script(error=LlmServerError(503, "upstream")),
            Script(text="done"),
        ]
    )
    client = LLMClient(
        provider, config=ModelConfig(model="mock-llm-v1"), retry=fast_retry, sleeper=sleeper
    )
    completion = await client.complete(conversation)

    assert completion.attempts == 3
    assert completion.text == "done"
    # 第一个延迟来自 Retry-After，第二个来自指数退避 base*2^(2-1)=0.2
    assert sleeper.delays == [0.5, pytest.approx(0.2)]
    assert len(provider.calls) == 3


async def test_retry_exhausted_raises_last_error(
    conversation: Conversation, fast_retry: RetryPolicy, sleeper: RecordingSleeper
) -> None:
    provider = ScriptedProvider(
        scripts=[
            Script(error=LlmServerError(503, "a")),
            Script(error=LlmServerError(503, "b")),
            Script(error=LlmServerError(503, "c")),
        ]
    )
    client = LLMClient(
        provider, config=ModelConfig(model="mock-llm-v1"), retry=fast_retry, sleeper=sleeper
    )
    with pytest.raises(LlmServerError):
        await client.complete(conversation)

    assert len(provider.calls) == 3
    # 只等待两次（第三次失败即放弃）
    assert sleeper.delays == [pytest.approx(0.1), pytest.approx(0.2)]


async def test_auth_error_is_not_retried(
    conversation: Conversation, fast_retry: RetryPolicy, sleeper: RecordingSleeper
) -> None:
    provider = ScriptedProvider(
        scripts=[Script(error=LlmAuthError(401, "bad key")), Script(text="never")]
    )
    client = LLMClient(
        provider, config=ModelConfig(model="mock-llm-v1"), retry=fast_retry, sleeper=sleeper
    )
    with pytest.raises(LlmAuthError):
        await client.complete(conversation)

    assert len(provider.calls) == 1
    assert sleeper.delays == []


async def test_client_error_is_not_retried(conversation: Conversation) -> None:
    provider = ScriptedProvider(
        scripts=[Script(error=LlmClientError(400, "bad request")), Script(text="never")]
    )
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=3))
    with pytest.raises(LlmClientError):
        await client.complete(conversation)
    assert len(provider.calls) == 1


async def test_timeout_maps_to_retryable_error(conversation: Conversation) -> None:
    provider = ScriptedProvider(scripts=[Script(delay_s=0.2, text="late")])
    client = LLMClient(
        provider,
        config=ModelConfig(model="mock-llm-v1", timeout_s=0.05),
        retry=RetryPolicy(max_attempts=1),
    )
    with pytest.raises(LlmTimeoutError):
        await client.complete(conversation)
    assert len(provider.calls) == 1


async def test_latency_uses_injected_clock(
    conversation: Conversation, clock: FakeClock
) -> None:
    provider = ScriptedProvider(scripts=[Script(text="done")])
    client = LLMClient(
        provider,
        config=ModelConfig(model="mock-llm-v1"),
        retry=RetryPolicy(max_attempts=1),
        clock=clock,
    )
    completion = await client.complete(conversation)
    # FakeClock 每次前进 0.25s，complete 读两次 -> 250ms
    assert completion.latency_ms == pytest.approx(250.0)


async def test_cost_uses_default_pricing(conversation: Conversation) -> None:
    provider = ScriptedProvider(
        scripts=[Script(text="x", usage=Usage(prompt_tokens=1000, completion_tokens=1000))]
    )
    client = LLMClient(
        provider,
        config=ModelConfig(model="gpt-4o-mini"),
        retry=RetryPolicy(max_attempts=1),
    )
    completion = await client.complete(conversation)
    # 0.00015 + 0.0006
    assert completion.cost_usd == pytest.approx(0.00075)


async def test_cost_pricing_is_injectable(conversation: Conversation) -> None:
    pricing = {"custom-model": ModelPricing(input_usd_per_1k=1.0, output_usd_per_1k=2.0)}
    provider = ScriptedProvider(
        scripts=[Script(text="x", usage=Usage(prompt_tokens=100, completion_tokens=100))]
    )
    client = LLMClient(
        provider,
        config=ModelConfig(model="custom-model"),
        retry=RetryPolicy(max_attempts=1),
        pricing=pricing,
    )
    completion = await client.complete(conversation)
    assert completion.cost_usd == pytest.approx(0.3)


def test_retry_policy_exponential_backoff_is_clamped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=1.5)
    assert policy.delay_for(1) == pytest.approx(1.0)
    assert policy.delay_for(2) == pytest.approx(1.5)
    assert policy.delay_for(3) == pytest.approx(1.5)


def test_retry_policy_rejects_invalid_attempts() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


async def test_repaired_usage_is_summed(
    conversation: Conversation,
) -> None:
    """修复重试时，用量/成本应累加，而不是只算最后一次。"""
    provider = ScriptedProvider(
        scripts=[
            Script(text='{"bad"', usage=Usage(prompt_tokens=100, completion_tokens=10)),
            Script(
                text='{"category":"storage","severity":"info","action":"clean"}',
                usage=Usage(prompt_tokens=200, completion_tokens=20),
            ),
        ]
    )
    from llm_api_lab.schemas import TriageResult

    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    result = await client.complete_structured(conversation, TriageResult, repair_attempts=1)
    assert result.repairs == 1
    assert result.completion.usage.prompt_tokens == 300
    assert result.completion.usage.completion_tokens == 30
