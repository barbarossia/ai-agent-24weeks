"""Provider 抽象与本地 mock 实现（**无需 API key、不访问网络**）。

架构分两层，刻意把"传输"与"策略"分开：

```text
LLMClient（策略：超时 / 重试 / 结构化 / 计费）
    │  依赖
    ▼
Provider（传输：把 ChatRequest 变成 ChatResponse）
    ├── MockProvider      确定性关键词分诊，用于演示 happy path
    ├── ScriptedProvider  按脚本依次返回文本/异常/延迟，用于测试坏路径
    └── OpenAICompatProvider（transport.py）真实 HTTP + SSE
```

因为两层返回**同一种** ``ChatResponse``，换 provider 时上层策略代码一行不改。
这也是"依赖倒置"在 LLM 客户端的落地：业务依赖 ``Provider`` 协议，不依赖 httpx。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .errors import LlmApiLabError
from .messages import Message, Role, estimate_tokens
from .models import ChatRequest, ChatResponse, StreamChunk, Usage

__all__ = [
    "Provider",
    "MockProvider",
    "Script",
    "ScriptedProvider",
]


@runtime_checkable
class Provider(Protocol):
    """把请求变成响应的传输抽象。"""

    name: str

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """发送一次非流式请求。"""
        ...

    def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        """发送一次流式请求，逐片产出增量。"""
        ...


def _last_user_content(request: ChatRequest) -> str:
    """取最后一条 user 消息的正文（mock/统计都需要它）。"""
    for message in reversed(request.messages):
        if message.role is Role.USER:
            return message.content
    return ""


def _estimated_usage(request: ChatRequest, output_text: str) -> Usage:
    """在没有真实 usage 时，用估算器补一个，保证下游始终有数可用。"""
    prompt_tokens = sum(estimate_tokens(m.content) + 4 for m in request.messages)
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=estimate_tokens(output_text),
    )


# --------------------------------------------------------------------------- #
# MockProvider：确定性、可解释、开箱即用
# --------------------------------------------------------------------------- #
# 关键词 → 类别（按顺序匹配，命中即停）。刻意用简单规则保证可测试。
_CATEGORY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("certificate", "cert", "密码", "password", "credential", "breach", "泄露", "攻击", "漏洞"), "security"),
    (("dns", "network", "网络", "ping", "latency", "延迟", "丢包", "gateway", "路由"), "network"),
    (("disk", "storage", "磁盘", "存储", "nas", "容量", "space", "备份"), "storage"),
    (("cpu", "memory", "内存", "esxi", "vm", "虚拟机", "service", "进程", "宕机", "负载"), "compute"),
)

_ACTION_BY_CATEGORY = {
    "network": "check_dns",
    "storage": "expand_or_clean_disk",
    "compute": "restart_service",
    "security": "rotate_credentials",
    "unknown": "collect_more_context",
}

_CRITICAL_WORDS = ("down", "宕机", "失败", "critical", "offline", "不可用", "100%", "挂了")
_WARNING_WORDS = ("slow", "慢", "很高", "high", "warning", "接近", "almost", "degraded", "频繁")


def _classify(question: str) -> dict[str, object]:
    """把自然语言问题映射成 ``TriageResult`` 形状的字典（纯函数，便于测试）。"""
    lowered = question.lower()

    category = "unknown"
    for keywords, name in _CATEGORY_RULES:
        if any(word in lowered for word in keywords):
            category = name
            break

    if any(word in lowered for word in _CRITICAL_WORDS):
        severity = "critical"
    elif any(word in lowered for word in _WARNING_WORDS):
        severity = "warning"
    else:
        severity = "info"

    return {
        "category": category,
        "severity": severity,
        "action": _ACTION_BY_CATEGORY[category],
        "confidence": 0.9 if category != "unknown" else 0.35,
        "reason": (
            f"matched keywords for category={category}"
            if category != "unknown"
            else "no strong signal in question"
        ),
    }


class MockProvider:
    """确定性 mock 模型：同样是问题，永远得到同样的 JSON。

    - 不联网、不需要 key；
    - 输出是**文本**（JSON 字符串），而不是对象 —— 特意保留"模型只会给你字符串"
      这一真实约束，让 Pydantic 校验这一步无法省略。
    """

    name = "mock"

    def __init__(
        self,
        *,
        chunk_size: int = 12,
        latency_s: float = 0.0,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        self._chunk_size = chunk_size
        self._latency_s = latency_s
        self.calls: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        if self._latency_s:
            await asyncio.sleep(self._latency_s)
        text = json.dumps(_classify(_last_user_content(request)), ensure_ascii=False)
        return ChatResponse(
            id=f"mock-{len(self.calls)}",
            model=request.model,
            content=text,
            finish_reason="stop",
            usage=_estimated_usage(request, text),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        self.calls.append(request)
        if self._latency_s:
            await asyncio.sleep(self._latency_s)
        text = json.dumps(_classify(_last_user_content(request)), ensure_ascii=False)
        for start in range(0, len(text), self._chunk_size):
            yield StreamChunk(delta=text[start : start + self._chunk_size])
        yield StreamChunk(
            finish_reason="stop",
            usage=_estimated_usage(request, text),
        )


# --------------------------------------------------------------------------- #
# ScriptedProvider：按脚本回放，用于确定性测试坏路径
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Script:
    """一次调用的剧本：正文、分片、异常或人为延迟，四选一组合。

    - ``error`` 非空 → 抛该异常（用于模拟 429/5xx/超时）；
    - ``delay_s``     → 先等待（用于触发客户端超时）；
    - ``chunks``      → 流式分片；``text`` 是完整正文（二者可只给一个）。
    """

    text: str = ""
    chunks: tuple[str, ...] = ()
    error: LlmApiLabError | None = None
    finish_reason: str = "stop"
    usage: Usage | None = None
    delay_s: float = 0.0

    def content(self) -> str:
        if self.text:
            return self.text
        return "".join(self.chunks)


class ScriptedProvider:
    """按 ``scripts`` 顺序逐次回放的 provider；脚本耗尽则报错。"""

    name = "scripted"

    def __init__(self, scripts: Sequence[Script]) -> None:
        self._scripts = list(scripts)
        self.calls: list[ChatRequest] = []

    def _take(self, request: ChatRequest) -> Script:
        self.calls.append(request)
        if not self._scripts:
            raise AssertionError(
                "scripted provider exhausted: add more Script entries for this call"
            )
        return self._scripts.pop(0)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        script = self._take(request)
        if script.delay_s:
            await asyncio.sleep(script.delay_s)
        if script.error is not None:
            raise script.error
        text = script.content()
        return ChatResponse(
            id=f"scripted-{len(self.calls)}",
            model=request.model,
            content=text,
            finish_reason=script.finish_reason,
            usage=script.usage or _estimated_usage(request, text),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        script = self._take(request)
        if script.delay_s:
            await asyncio.sleep(script.delay_s)
        if script.error is not None:
            raise script.error
        parts = script.chunks or ((script.text,) if script.text else ())
        for part in parts:
            yield StreamChunk(delta=part)
        yield StreamChunk(
            finish_reason=script.finish_reason,
            usage=script.usage or _estimated_usage(request, script.content()),
        )
