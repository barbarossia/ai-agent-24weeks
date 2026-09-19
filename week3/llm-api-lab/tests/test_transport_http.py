"""HTTP 传输层测试：用 ``httpx.MockTransport`` 假扮服务器，零网络。

覆盖：请求体拼装、响应解析、usage 缺失兜底、reasoning 透传、
HTTP 状态码 → 异常树映射、鉴权头安全默认、SSE 流式解析。
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from llm_api_lab.client import LLMClient, RetryPolicy
from llm_api_lab.errors import (
    ConfigurationError,
    LlmAuthError,
    LlmClientError,
    LlmRateLimitError,
    LlmServerError,
)
from llm_api_lab.messages import Conversation
from llm_api_lab.models import ChatRequest, ModelConfig
from llm_api_lab.schemas import TriageResult, json_response_format
from llm_api_lab.transport import OpenAICompatProvider

Handler = Callable[[httpx.Request], httpx.Response]

OPENAI_OK = {
    "id": "chatcmpl-1",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "message": {"role": "assistant", "content": '{"category":"network"}'},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
}


def make_provider(
    handler: Handler, *, api_key: str | None = None
) -> OpenAICompatProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider(base_url="http://test/v1", api_key=api_key, client=client)


async def test_complete_parses_openai_shape(conversation: Conversation) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json=OPENAI_OK))
    client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini"))
    completion = await client.complete(conversation)

    assert completion.text == '{"category":"network"}'
    assert completion.model == "gpt-4o-mini"
    assert completion.finish_reason == "stop"
    assert completion.usage.total_tokens == 48


async def test_missing_usage_is_estimated(conversation: Conversation) -> None:
    body = dict(OPENAI_OK)
    body.pop("usage")
    provider = make_provider(lambda request: httpx.Response(200, json=body))
    client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini"))
    completion = await client.complete(conversation)

    assert completion.usage.prompt_tokens > 0
    assert completion.usage.completion_tokens > 0


async def test_reasoning_is_passed_through(conversation: Conversation) -> None:
    body = json.loads(json.dumps(OPENAI_OK))
    body["choices"][0]["message"]["reasoning_content"] = "先看磁盘水位……"
    provider = make_provider(lambda request: httpx.Response(200, json=body))

    response = await provider.complete(
        ChatRequest(model="gpt-4o-mini", messages=tuple(conversation.messages))
    )
    assert response.reasoning == "先看磁盘水位……"


async def test_request_payload_includes_schema_and_messages(
    conversation: Conversation,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=OPENAI_OK)

    provider = make_provider(handler)
    client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini", temperature=0.3))
    await client.complete(
        conversation, response_format=json_response_format(TriageResult)
    )

    assert captured["model"] == "gpt-4o-mini"
    assert captured["temperature"] == pytest.approx(0.3)
    assert captured["stream"] is False
    messages = captured["messages"]
    assert isinstance(messages, list) and messages[0]["role"] == "system"
    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "TriageResult"


async def test_no_api_key_means_no_authorization_header(
    conversation: Conversation,
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "<absent>")
        return httpx.Response(200, json=OPENAI_OK)

    provider = make_provider(handler)
    await LLMClient(provider, config=ModelConfig(model="gpt-4o-mini")).complete(
        conversation
    )
    assert seen["authorization"] == "<absent>"


async def test_explicit_api_key_is_sent(conversation: Conversation) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "<absent>")
        return httpx.Response(200, json=OPENAI_OK)

    provider = make_provider(handler, api_key="test-key-not-a-real-secret")
    await LLMClient(provider, config=ModelConfig(model="gpt-4o-mini")).complete(
        conversation
    )
    assert seen["authorization"] == "Bearer test-key-not-a-real-secret"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LlmAuthError),
        (403, LlmAuthError),
        (400, LlmClientError),
        (404, LlmClientError),
        (500, LlmServerError),
        (503, LlmServerError),
    ],
)
async def test_status_codes_map_to_error_tree(
    conversation: Conversation, status: int, expected: type[Exception]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    provider = make_provider(handler)
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    with pytest.raises(expected) as excinfo:
        await client.complete(conversation)
    assert "boom" in str(excinfo.value)


async def test_429_carries_retry_after(conversation: Conversation) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "slow down"}},
            headers={"retry-after": "2"},
        )

    provider = make_provider(handler)
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    with pytest.raises(LlmRateLimitError) as excinfo:
        await client.complete(conversation)
    assert excinfo.value.retry_after_s == pytest.approx(2.0)


def test_base_url_is_required() -> None:
    with pytest.raises(ConfigurationError):
        OpenAICompatProvider(base_url="")


async def test_stream_parses_sse_events(conversation: Conversation) -> None:
    sse = (
        'data: {"choices":[{"delta":{"content":"{\\"a\\":"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"1}"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=sse, headers={"content-type": "text/event-stream"}
        )

    provider = make_provider(handler)
    client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini"))
    assembled = await client.collect_stream(conversation)
    assert assembled == '{"a":1}'


async def test_stream_http_error_maps_to_error_tree(
    conversation: Conversation,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"message": "slow down"}}, headers={"retry-after": "1"}
        )

    provider = make_provider(handler)
    client = LLMClient(provider, config=ModelConfig(model="gpt-4o-mini"))
    with pytest.raises(LlmRateLimitError):
        async for _ in client.stream(conversation):
            pass
