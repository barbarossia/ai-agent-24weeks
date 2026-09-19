"""示例 2：Streaming —— 逐片接收 token，改善首字延迟。

运行：``uv run python examples/02_streaming_tokens.py``

要点：流式与一次性返回的总 token 数一致，区别只在**何时拿到第一个字**。
用流式时，一旦开始产出就不适合中途重试（会重复内容），这是 Week 4+ 的话题。
"""

from __future__ import annotations

import asyncio

from llm_api_lab.client import LLMClient
from llm_api_lab.messages import Conversation, Message, Role
from llm_api_lab.models import ModelConfig
from llm_api_lab.providers import MockProvider


def build_conversation(question: str) -> Conversation:
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content="你是 HomeLab 运维助手，用一句话回答。"),
            Message(role=Role.USER, content=question),
        ]
    )


async def main() -> int:
    provider = MockProvider(chunk_size=10)
    client = LLMClient(provider, config=ModelConfig(model="mock-llm-v1"))
    conversation = build_conversation("NAS 磁盘快满了，怎么办？")

    chunks = 0
    print("streaming    : ", end="", flush=True)
    async for delta in client.stream(conversation):
        chunks += 1
        print(delta, end="", flush=True)
    print()

    assembled = await client.collect_stream(conversation)
    print(f"chunks       : {chunks}")
    print(f"assembled    : {assembled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
