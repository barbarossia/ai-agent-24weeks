"""LLM 客户端：把"传输"包上一层**调用策略**。

策略包括（本文件的核心学习点）：
- **超时**：``asyncio.wait_for`` 给每次调用设预算，超时抛可重试异常；
- **重试**：只对 ``RetryableError`` 退避重试，且尊重 429 的 ``Retry-After``；
- **结构化输出**：``complete_structured`` 做 JSON 解析 + Pydantic 校验，
  失败时追加"修复消息"再试（invalid output 处理）；
- **用量与成本**：token / 延迟 / 成本随结果一起返回，让约束可见；
- **上下文预算**：发送前检查是否超出窗口。

可测性设计：``sleeper`` 与 ``clock`` 可注入，测试里用假实现即可**不真实等待**、
**不依赖墙钟**地断言退避序列与延迟统计。
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import LlmRateLimitError, LlmTimeoutError, RetryableError, StructuredOutputError
from .messages import ContextWindow, Conversation, Message, Role
from .models import (
    ChatRequest,
    ChatResponse,
    ModelConfig,
    ResponseFormat,
    Usage,
)
from .providers import Provider
from .schemas import json_response_format
from .usage import DEFAULT_PRICING, ModelPricing, estimate_cost_usd, pricing_for

__all__ = [
    "RetryPolicy",
    "Completion",
    "StructuredResult",
    "LLMClient",
    "extract_json",
    "parse_structured",
]

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class RetryPolicy:
    """指数退避重试策略（jitter=0 时完全确定，便于测试）。"""

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_s < 0 or self.max_delay_s < 0 or self.jitter < 0:
            raise ValueError("delays and jitter must be >= 0")

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """第 ``attempt`` 次失败后的等待秒数（1-based）：``base * 2^(attempt-1)``，封顶。"""
        raw = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        if self.jitter <= 0 or rng is None:
            return raw
        return raw + rng.uniform(0.0, self.jitter * raw)


class Completion(BaseModel):
    """一次（或多次重试/修复合并后的）补全结果，自带用量、延迟与成本。"""

    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    finish_reason: str
    usage: Usage
    latency_ms: float
    attempts: int
    cost_usd: float


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """结构化调用的返回：校验后的对象 + 背后的补全统计。"""

    value: T
    completion: Completion
    repairs: int


def extract_json(text: str) -> str:
    """从模型输出里尽力抠出 JSON 文本。

    真实模型很爱加 ``\`\`\`json`` 围栏或前后解释；这里做**宽容提取**，
    真正的合法性仍交给 ``json.loads`` + Pydantic 判断（宽容不等于放行）。
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def parse_structured(text: str, schema: type[T]) -> T:
    """把模型文本解析并校验成 ``schema`` 实例；任何问题都归一为 ``StructuredOutputError``。"""
    candidate = extract_json(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            f"model output is not valid JSON: {exc.msg}",
            raw_text=text,
            reason="invalid_json",
        ) from exc
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        details = [
            f"{'.'.join(str(part) for part in error.get('loc', ()))}: {error.get('msg', '')}"
            for error in exc.errors()[:5]
        ]
        raise StructuredOutputError(
            "model output failed schema validation",
            raw_text=text,
            reason="schema_mismatch",
            validation_errors=details,
        ) from exc


def _combine_usage(completions: list[Completion]) -> Usage:
    return Usage(
        prompt_tokens=sum(item.usage.prompt_tokens for item in completions),
        completion_tokens=sum(item.usage.completion_tokens for item in completions),
    )


class LLMClient:
    """面向业务的高层客户端：``complete`` / ``complete_structured`` / ``stream``。"""

    def __init__(
        self,
        provider: Provider,
        *,
        config: ModelConfig | None = None,
        retry: RetryPolicy | None = None,
        pricing: Mapping[str, ModelPricing] | None = None,
        context_window: ContextWindow | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or ModelConfig()
        self._retry = retry or RetryPolicy()
        self._pricing = pricing if pricing is not None else DEFAULT_PRICING
        self._context_window = context_window
        self._sleep = sleeper or asyncio.sleep
        self._clock = clock or __import__("time").perf_counter
        self._rng = rng

    # ------------------------------------------------------------------ #
    # 请求装配 / 预算校验
    # ------------------------------------------------------------------ #
    @property
    def config(self) -> ModelConfig:
        return self._config

    def _ensure_fits(self, conversation: Conversation) -> None:
        if self._context_window is not None:
            self._context_window.ensure_fits(conversation, model=self._config.model)

    def _build_request(
        self,
        conversation: Conversation,
        *,
        stream: bool,
        response_format: ResponseFormat | None = None,
    ) -> ChatRequest:
        return ChatRequest(
            model=self._config.model,
            messages=tuple(conversation.messages),
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_output_tokens,
            response_format=response_format or ResponseFormat(),
            stream=stream,
            stop=self._config.stop,
        )

    # ------------------------------------------------------------------ #
    # 重试 / 超时
    # ------------------------------------------------------------------ #
    def _delay_for(self, error: RetryableError, attempt: int) -> float:
        """429 优先用服务端给的 Retry-After；其余走指数退避。"""
        if isinstance(error, LlmRateLimitError) and error.retry_after_s is not None:
            return min(error.retry_after_s, self._retry.max_delay_s)
        return self._retry.delay_for(attempt, self._rng)

    async def _invoke(self, request: ChatRequest) -> ChatResponse:
        """单次调用，叠加超时预算。"""
        call = self._provider.complete(request)
        timeout = self._config.timeout_s
        if timeout is None:
            return await call
        try:
            return await asyncio.wait_for(call, timeout=timeout)
        except TimeoutError as exc:
            raise LlmTimeoutError(
                f"request timed out after {timeout}s (model={request.model})"
            ) from exc

    async def _request_with_retry(self, request: ChatRequest) -> tuple[ChatResponse, int]:
        attempts = 0
        while attempts < self._retry.max_attempts:
            attempts += 1
            try:
                return await self._invoke(request), attempts
            except RetryableError as error:
                if attempts >= self._retry.max_attempts:
                    raise
                await self._sleep(self._delay_for(error, attempts))
        raise AssertionError("unreachable: retry loop must return or raise")

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #
    async def complete(
        self,
        conversation: Conversation,
        *,
        response_format: ResponseFormat | None = None,
    ) -> Completion:
        """非流式补全，返回文本 + 用量 + 延迟 + 成本 + 实际尝试次数。"""
        self._ensure_fits(conversation)
        request = self._build_request(
            conversation, stream=False, response_format=response_format
        )
        started = self._clock()
        response, attempts = await self._request_with_retry(request)
        latency_ms = (self._clock() - started) * 1000.0
        return Completion(
            text=response.content,
            model=response.model,
            finish_reason=response.finish_reason,
            usage=response.usage,
            latency_ms=latency_ms,
            attempts=attempts,
            cost_usd=estimate_cost_usd(
                response.usage, pricing_for(request.model, self._pricing)
            ),
        )

    async def complete_structured(
        self,
        conversation: Conversation,
        schema: type[T],
        *,
        repair_attempts: int = 1,
    ) -> StructuredResult[T]:
        """要求模型输出符合 ``schema`` 的结构化结果，失败时尝试修复。

        修复策略：把模型的坏输出作为 ``assistant`` 消息回灌，再追加一条
        ``user`` 纠正指令，让模型"看着自己的错误"重写。``repair_attempts=0`` 表示不修复。
        """
        if repair_attempts < 0:
            raise ValueError("repair_attempts must be >= 0")

        current = conversation
        completions: list[Completion] = []
        last_error: StructuredOutputError | None = None

        for attempt in range(repair_attempts + 1):
            self._ensure_fits(current)
            completion = await self.complete(
                current, response_format=json_response_format(schema)
            )
            completions.append(completion)
            try:
                value = parse_structured(completion.text, schema)
            except StructuredOutputError as error:
                last_error = error
                if attempt >= repair_attempts:
                    raise
                current = self._repair_conversation(current, completion.text, error)
                continue

            return StructuredResult(
                value=value,
                completion=self._merge_completions(completions, completion),
                repairs=attempt,
            )

        raise last_error or AssertionError("unreachable: structured loop must return or raise")

    @staticmethod
    def _repair_conversation(
        conversation: Conversation,
        invalid_text: str,
        error: StructuredOutputError,
    ) -> Conversation:
        detail = "; ".join(error.validation_errors)
        correction = (
            f"上一条输出不符合要求（{error.reason}{(': ' + detail) if detail else ''}）。"
            "请只输出一个合法 JSON 对象，不要 Markdown 代码块或任何额外文字。"
        )
        return Conversation(
            messages=[
                *conversation.messages,
                Message(role=Role.ASSISTANT, content=invalid_text.strip() or "<empty>"),
                Message(role=Role.USER, content=correction),
            ]
        )

    @staticmethod
    def _merge_completions(
        completions: list[Completion], final: Completion
    ) -> Completion:
        """把修复过程中所有尝试的用量/延迟/成本累加 —— 你确实为它们付了钱。"""
        return Completion(
            text=final.text,
            model=final.model,
            finish_reason=final.finish_reason,
            usage=_combine_usage(completions),
            latency_ms=sum(item.latency_ms for item in completions),
            attempts=sum(item.attempts for item in completions),
            cost_usd=sum(item.cost_usd for item in completions),
        )

    async def stream(self, conversation: Conversation) -> AsyncIterator[str]:
        """流式补全，逐片产出文本增量。

        说明：本实现**只在首个 token 之前不做重试**之外保持简单 —— 一旦开始产出，
        半途重试会导致重复内容，属于 Week 4+ 的话题（记录为练习）。
        """
        self._ensure_fits(conversation)
        request = self._build_request(conversation, stream=True)
        async for chunk in self._provider.stream(request):
            if chunk.delta:
                yield chunk.delta

    async def collect_stream(self, conversation: Conversation) -> str:
        """把流式增量拼回完整文本（便于断言与展示）。"""
        parts = [delta async for delta in self.stream(conversation)]
        return "".join(parts)
