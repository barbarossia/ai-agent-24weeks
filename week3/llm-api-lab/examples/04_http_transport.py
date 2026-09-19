"""示例 4：真实 HTTP 传输的骨架 —— 用 ``httpx.MockTransport`` 假扮服务器。

运行：``uv run python examples/04_http_transport.py``

这里走的是与真实调用**完全相同**的代码路径（拼请求体 → 发 HTTP → 判状态码 →
解析响应 JSON），只是把 socket 换成进程内的假 handler：
既能验证"响应解析 / SSE 解析 / 状态码映射"，又**不联网、不需要 key**。

想接真实端点时，把 ``transport=...`` 去掉、base_url 换成你的网关，
并**显式**传入 api_key（本项目不读取任何环境变量或隐式凭据）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from llm_api_lab.client import LLMClient
from llm_api_lab.errors import LlmRateLimitError
from llm_api_lab.messages import Conversation, Message, Role
from llm_api_lab.models import ModelConfig
from llm_api_lab.transport import OpenAICompatProvider


def conversation() -> Conversation:
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content="你是 HomeLab 运维助手。"),
            Message(role=Role.USER, content="NAS 磁盘快满了"),
        ]
    )


def fake_server(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode("utf-8"))
    if body["model"] == "rate-limited-model":
        return httpx.Response(
            429,
            json={"error": {"message": "rate limit exceeded"}},
            headers={"retry-after": "2"},
        )
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-fake-1",
            "model": body["model"],
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"category":"storage","severity":"critical"}',
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 11,
                "total_tokens": 53,
            },
        },
    )


async def main() -> int:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_server)) as http:
        provider = OpenAICompatProvider(base_url="http://test/v1", client=http)

        ok_client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini"))
        completion = await ok_client.complete(conversation())
        print(f"[200] content={completion.text}")
        print(f"[200] usage={completion.usage.model_dump()} cost=${completion.cost_usd:.8f}")

        limited_client = LLMClient(
            provider, config=ModelConfig(model="rate-limited-model")
        )
        try:
            await limited_client.complete(conversation())
        except LlmRateLimitError as exc:
            print(f"[429] mapped to LlmRateLimitError retry_after_s={exc.retry_after_s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
