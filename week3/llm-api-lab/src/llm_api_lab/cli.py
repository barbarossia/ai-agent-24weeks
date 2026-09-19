"""可运行的命令行演示：把 Week 3 的每个概念变成一条可观察的命令。

```bash
uv run llm-api-lab demo          # User Question → LLM → Structured JSON → Pydantic
uv run llm-api-lab schema        # 看 Pydantic 生成的 JSON Schema
uv run llm-api-lab invalid-json  # 模型先给坏 JSON，客户端修复重试
uv run llm-api-lab retry         # 429 / 503 的退避重试（演示 sleeper 记录，不真等待）
uv run llm-api-lab stream        # 流式逐片输出
uv run llm-api-lab budget        # 超过上下文窗口时提前拒绝
```

**所有命令只使用 mock / scripted provider**：不需要 key、不联网、不产生费用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from .errors import (
    ContextWindowExceededError,
    LlmApiLabError,
    LlmRateLimitError,
    LlmServerError,
)
from .client import LLMClient, RetryPolicy
from .messages import ContextWindow, Conversation, Message, Role
from .models import ModelConfig
from .providers import MockProvider, Script, ScriptedProvider
from .schemas import INCIDENT_SYSTEM_PROMPT, TriageResult, describe_schema

__all__ = ["build_parser", "main"]

_DEFAULT_QUESTION = "NAS 磁盘快满了，服务很慢，怎么办？"

# 演示"模型先给坏输出"的固定剧本：第一段是被截断的 JSON。
_BAD_JSON = '{"category": "storage", "severity": "critical"'
_GOOD_JSON = (
    '{"category":"storage","severity":"warning","action":"expand_or_clean_disk",'
    '"confidence":0.88,"reason":"disk usage near capacity slows NAS services"}'
)


def structured_conversation(question: str) -> Conversation:
    """system（含 schema）+ user 问题：结构化输出的标准拼装。"""
    system = f"{INCIDENT_SYSTEM_PROMPT}\n\n{describe_schema(TriageResult)}"
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=question),
        ]
    )


def plain_conversation(question: str) -> Conversation:
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content=INCIDENT_SYSTEM_PROMPT),
            Message(role=Role.USER, content=question),
        ]
    )


def _new_client(
    provider: object,
    *,
    retry: RetryPolicy | None = None,
    sleeper: object = None,
    window: ContextWindow | None = None,
) -> LLMClient:
    from .providers import Provider  # 局部导入，避免顶层循环依赖

    return LLMClient(
        provider,  # type: ignore[arg-type]
        config=ModelConfig(model="mock-llm-v1", timeout_s=5.0),
        retry=retry or RetryPolicy(max_attempts=1),
        context_window=window,
        sleeper=sleeper,  # type: ignore[arg-type]
    )


async def _demo(args: argparse.Namespace) -> int:
    provider = MockProvider()
    client = _new_client(provider)
    result = await client.complete_structured(
        structured_conversation(args.question), TriageResult
    )
    print(f"question    : {args.question}")
    print(f"raw (model) : {result.completion.text}")
    print(f"validated   : {result.value.model_dump_json(ensure_ascii=False)}")
    print(f"repairs     : {result.repairs}")
    print(f"usage       : {result.completion.usage.model_dump()}")
    print(
        f"latency/cost: {result.completion.latency_ms:.2f} ms / "
        f"${result.completion.cost_usd:.6f}"
    )
    print("说明：raw 是**字符串**，validated 才是可信对象 —— 中间那道闸门就是 Pydantic。")
    return 0


async def _schema(_args: argparse.Namespace) -> int:
    print(json.dumps(TriageResult.model_json_schema(), ensure_ascii=False, indent=2))
    return 0


async def _invalid_json(_args: argparse.Namespace) -> int:
    provider = ScriptedProvider(
        scripts=[Script(text=_BAD_JSON), Script(text=_GOOD_JSON)]
    )
    client = _new_client(provider, retry=RetryPolicy(max_attempts=1))
    result = await client.complete_structured(
        structured_conversation("NAS 磁盘快满了"), TriageResult
    )
    print(f"attempt 1   : {_BAD_JSON}   <- 非法 JSON，被 StructuredOutputError 拦下")
    print(f"attempt 2   : {result.completion.text}")
    print(f"repairs     : {result.repairs}（修复重试次数）")
    print(f"provider 调用次数: {len(provider.calls)}")
    print(f"validated   : {result.value.model_dump_json(ensure_ascii=False)}")
    return 0


async def _retry(_args: argparse.Namespace) -> int:
    delays: list[float] = []

    async def sleeper(seconds: float) -> None:
        delays.append(seconds)  # 只记录，不真的等待，演示因此是秒回

    provider = ScriptedProvider(
        scripts=[
            Script(error=LlmRateLimitError("429 too many requests", retry_after_s=0.2)),
            Script(error=LlmServerError(503, "upstream unavailable")),
            Script(text=_GOOD_JSON),
        ]
    )
    client = _new_client(
        provider,
        retry=RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=1.0),
        sleeper=sleeper,
    )
    completion = await client.complete(plain_conversation("NAS 磁盘快满了"))
    print(f"attempts    : {completion.attempts}（1 次 429 + 1 次 503 + 1 次成功）")
    print(f"delays      : {delays}   <- 第一个来自 Retry-After，第二个来自指数退避")
    print(f"finish      : {completion.finish_reason}")
    print("说明：只有可重试错误才退避重试；4xx 鉴权/参数错误会立刻失败，避免白烧配额。")
    return 0


async def _stream(_args: argparse.Namespace) -> int:
    provider = MockProvider(chunk_size=10)
    client = _new_client(provider)
    print("delta 流   : ", end="", flush=True)
    async for delta in client.stream(plain_conversation("NAS 磁盘快满了")):
        print(delta, end="", flush=True)
    print()
    assembled = await client.collect_stream(plain_conversation("NAS 磁盘快满了"))
    print(f"assembled  : {assembled}")
    print("说明：streaming 改善的是**首字延迟**体验，总量与费用与一次性返回一致。")
    return 0


async def _budget(_args: argparse.Namespace) -> int:
    window = ContextWindow(max_context_tokens=64, reserved_output_tokens=16)
    client = _new_client(MockProvider(), window=window)
    huge = "网络抖动 " * 200
    try:
        await client.complete(plain_conversation(huge))
    except ContextWindowExceededError as exc:
        print(f"blocked before sending: {exc}")
        print(
            f"estimated={exc.estimated_tokens} > available={exc.available_input_tokens}"
            "  -> 提前拒绝，而不是发出去等 400/等账单"
        )
        return 0
    print("unexpected: request was not blocked")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-api-lab",
        description="Week 3 LLM API 基础演示（全程 mock，无需 API key）",
    )
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="结构化输出 happy path")
    demo.add_argument("--question", default=_DEFAULT_QUESTION)
    sub.add_parser("schema", help="打印 TriageResult 的 JSON Schema")
    sub.add_parser("invalid-json", help="展示 invalid output 的修复重试")
    sub.add_parser("retry", help="展示 429/503 退避重试")
    sub.add_parser("stream", help="展示流式增量输出")
    sub.add_parser("budget", help="展示上下文窗口预算保护")
    return parser


_HANDLERS = {
    "demo": _demo,
    "schema": _schema,
    "invalid-json": _invalid_json,
    "retry": _retry,
    "stream": _stream,
    "budget": _budget,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return asyncio.run(_HANDLERS[args.command](args))
    except LlmApiLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
