"""真实 HTTP 传输层：OpenAI 兼容 ``/chat/completions`` + SSE 流式解析。

这一层负责"线缆"上的事：拼 JSON、加请求头、判断 HTTP 状态码、把响应解析成
强类型 ``ChatResponse``、把 SSE 文本流解析成 ``StreamChunk``。

**安全边界（重点）**
- 构造器**绝不读取** ``os.environ`` 或任何隐式凭据；``api_key`` 必须由调用者显式传入；
- 未提供 key 时，请求头里就不会出现 ``Authorization``（安全默认）；
- 缺 ``base_url`` 直接抛 ``ConfigurationError``，而不是悄悄连到某个默认端点；
- 本项目所有测试与示例都注入 ``httpx.MockTransport``，**不访问网络、不产生费用**。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Iterator
from typing import Any

import httpx

from .errors import (
    ConfigurationError,
    LlmAuthError,
    LlmClientError,
    LlmConnectionError,
    LlmRateLimitError,
    LlmServerError,
    LlmTimeoutError,
)
from .messages import estimate_tokens
from .models import ChatRequest, ChatResponse, StreamChunk, Usage

__all__ = [
    "OpenAICompatProvider",
    "SSE_DONE_SENTINEL",
    "iter_sse_events",
]

SSE_DONE_SENTINEL = "[DONE]"


def _parse_sse_line(line: str) -> tuple[bool, dict[str, Any] | None]:
    """解析一行 SSE。

    返回 ``(done, event)``：``done=True`` 表示遇到 ``data: [DONE]``；
    注释行（``:`` 开头）、空行、非 ``data:`` 行、坏 JSON 一律安全跳过。
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(":") or not stripped.startswith("data:"):
        return False, None
    payload = stripped[len("data:") :].strip()
    if payload == SSE_DONE_SENTINEL:
        return True, None
    if not payload:
        return False, None
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return False, None
    if not isinstance(event, dict):
        return False, None
    return False, event


def iter_sse_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """把 SSE 文本行（同步可迭代）解析成事件 dict 序列；便于单元测试。"""
    for line in lines:
        done, event = _parse_sse_line(line)
        if done:
            return
        if event is not None:
            yield event


def _usage_from_wire(raw: Any) -> Usage | None:
    """解析 OpenAI 形状的 usage；字段缺失返回 ``None``，由上层决定是否估算。"""
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return Usage(prompt_tokens=max(0, prompt), completion_tokens=max(0, completion))


def _chunk_from_event(event: dict[str, Any]) -> StreamChunk:
    """把一条 OpenAI 流式事件映射成 ``StreamChunk``。"""
    delta_text = ""
    finish_reason: str | None = None
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                delta_text = content
        raw_finish = choice.get("finish_reason")
        if isinstance(raw_finish, str):
            finish_reason = raw_finish
    return StreamChunk(
        delta=delta_text,
        finish_reason=finish_reason,
        usage=_usage_from_wire(event.get("usage")),
    )


def _request_payload(request: ChatRequest) -> dict[str, Any]:
    """把 ``ChatRequest`` 序列化成 OpenAI 兼容请求体。"""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [
            {"role": message.role.value, "content": message.content}
            for message in request.messages
        ],
        "temperature": request.temperature,
        "max_tokens": request.max_output_tokens,
        "stream": request.stream,
    }
    if request.stop:
        payload["stop"] = list(request.stop)
    if request.response_format.type == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif (
        request.response_format.type == "json_schema"
        and request.response_format.json_schema is not None
    ):
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": request.response_format.json_schema,
        }
    return payload


def _response_from_wire(
    event: dict[str, Any],
    request: ChatRequest,
) -> ChatResponse:
    """把 OpenAI 形状的完整响应解析成 ``ChatResponse``（响应解析的关键一步）。"""
    content = ""
    finish_reason = "stop"
    reasoning: str | None = None
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if isinstance(message, dict):
            raw_content = message.get("content")
            if isinstance(raw_content, str):
                content = raw_content
            raw_reasoning = message.get("reasoning_content") or message.get("reasoning")
            if isinstance(raw_reasoning, str):
                reasoning = raw_reasoning
        raw_finish = choice.get("finish_reason")
        if isinstance(raw_finish, str):
            finish_reason = raw_finish

    usage = _usage_from_wire(event.get("usage"))
    if usage is None:
        # 厂商偶尔不返回 usage：用估算器兜底，保证计费/预算链路不断。
        usage = Usage(
            prompt_tokens=sum(
                estimate_tokens(m.content) + 4 for m in request.messages
            ),
            completion_tokens=estimate_tokens(content),
        )

    model = event.get("model")
    identifier = event.get("id")
    return ChatResponse(
        id=identifier if isinstance(identifier, str) else "unknown",
        model=model if isinstance(model, str) else request.model,
        content=content,
        finish_reason=finish_reason,
        usage=usage,
        reasoning=reasoning,
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _error_message(response: httpx.Response) -> str:
    """尽量从错误响应体里提取一句人类可读信息（不回显敏感头）。"""
    try:
        data = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:200] if text else response.reason_phrase
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(data.get("message"), str):
            return data["message"]
    return response.reason_phrase


class OpenAICompatProvider:
    """OpenAI 兼容 HTTP provider。

    典型用法（真实场景，本项目不执行）：

    ```python
    async with OpenAICompatProvider(base_url="https://api.example.com/v1",
                                    api_key=key) as provider:
        ...
    ```

    测试用法（本项目实际使用，零网络）：

    ```python
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(base_url="http://test/v1", client=client)
    ```
    """

    name = "openai-compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ConfigurationError("base_url is required (no implicit default endpoint)")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._extra_headers = dict(extra_headers or {})

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self._extra_headers}
        # 安全默认：没有显式 api_key 就不发送 Authorization 头。
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        """把 HTTP 状态码映射成异常树：可重试的与不可重试的分开。"""
        status = response.status_code
        if status < 400:
            return
        detail = _error_message(response)
        if status == 429:
            raise LlmRateLimitError(
                f"rate limited ({status}): {detail}",
                retry_after_s=_retry_after_seconds(response),
            )
        if status in (401, 403):
            raise LlmAuthError(status, detail)
        if 400 <= status < 500:
            raise LlmClientError(status, detail)
        raise LlmServerError(status, detail)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        payload = _request_payload(request)
        try:
            response = await self._client.post(
                self.endpoint, json=payload, headers=self._headers()
            )
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(f"request to {self.endpoint} timed out") from exc
        except httpx.TransportError as exc:
            raise LlmConnectionError(f"connection error: {exc}") from exc

        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmClientError(response.status_code, "response body is not valid JSON") from exc
        if not isinstance(data, dict):
            raise LlmClientError(response.status_code, "response body is not a JSON object")
        return _response_from_wire(data, request)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        payload = _request_payload(request)
        payload["stream"] = True
        try:
            async with self._client.stream(
                "POST", self.endpoint, json=payload, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    await response.aread()  # 错误体需要先读出来才能解析
                    self._raise_for_status(response)
                async for line in response.aiter_lines():
                    done, event = _parse_sse_line(line)
                    if done:
                        break
                    if event is not None:
                        yield _chunk_from_event(event)
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(f"stream to {self.endpoint} timed out") from exc
        except httpx.TransportError as exc:
            raise LlmConnectionError(f"connection error: {exc}") from exc

    async def aclose(self) -> None:
        """只关闭自己创建的 client；外部注入的由外部负责。"""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatProvider:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
