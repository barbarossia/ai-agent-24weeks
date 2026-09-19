"""异常树：把 LLM API 调用失败分成**可重试**与**不可重试**两类。

分层演进（同一套"异常树"思想，最外层消费者在变）：
- Week 1：异常树 + 进程退出码（CLI）；
- Week 2：异常树 + HTTP 状态码 + JSON 外壳（FastAPI）；
- Week 3：异常树 + **重试语义**（LLM 客户端）—— 这是本文件的核心增量。

关键区分：
- ``RetryableError``   暂时性故障（超时 / 连接失败 / 429 限流 / 5xx），
  退避后重试是安全的；
- 其余 ``LlmApiError`` 不可重试（400/401/404 等）——**重试只会浪费钱和配额**。

对照 C#：相当于用一棵 ``Exception`` 继承树 + ``is`` 判断来驱动 Polly 的重试策略。
"""

from __future__ import annotations

__all__ = [
    "LlmApiLabError",
    "LlmApiError",
    "RetryableError",
    "LlmTimeoutError",
    "LlmConnectionError",
    "LlmRateLimitError",
    "LlmServerError",
    "LlmClientError",
    "LlmAuthError",
    "ConfigurationError",
    "StructuredOutputError",
    "ContextWindowExceededError",
]


class LlmApiLabError(Exception):
    """本项目所有异常的基类（catch-all 兜底用）。"""


class LlmApiError(LlmApiLabError):
    """调用模型 API 失败。"""


# --------------------------------------------------------------------------- #
# 可重试：暂时性故障
# --------------------------------------------------------------------------- #
class RetryableError(LlmApiError):
    """**标记基类**：表示"现在失败，稍后重试可能成功"。

    客户端只对 ``RetryableError`` 子树做退避重试。
    """


class LlmTimeoutError(RetryableError):
    """请求超过配置的超时预算仍未完成。"""


class LlmConnectionError(RetryableError):
    """TCP/TLS 层连接失败（DNS、握手、连接被重置等）。"""


class LlmRateLimitError(RetryableError):
    """HTTP 429：请求过快或配额耗尽。

    ``retry_after_s`` 来自响应的 ``Retry-After`` 头（若提供）；
    客户端优先按它等待，而不是按自己的退避公式。
    """

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LlmServerError(RetryableError):
    """HTTP 5xx：上游模型服务自身出错。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"server error {status_code}: {message}")
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# 不可重试：请求/鉴权错误
# --------------------------------------------------------------------------- #
class LlmClientError(LlmApiError):
    """HTTP 4xx：请求本身有问题，重试不会有不同结果。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"client error {status_code}: {message}")
        self.status_code = status_code


class LlmAuthError(LlmClientError):
    """HTTP 401/403：缺少或无效凭据。**绝不要把 key 写进异常消息。**"""


class ConfigurationError(LlmApiLabError):
    """客户端配置缺失或非法（例如真实传输未提供 base_url）。"""


# --------------------------------------------------------------------------- #
# 结构化输出 / 上下文预算
# --------------------------------------------------------------------------- #
class StructuredOutputError(LlmApiLabError):
    """模型输出无法解析为期望的结构（JSON 语法错误或 schema 校验失败）。

    携带原始文本与失败原因，便于上层"修复重试"或记录可观测证据。
    ``model_dump`` 时务必小心：原始文本可能含用户数据，不应直接写日志。
    """

    def __init__(
        self,
        message: str,
        *,
        raw_text: str = "",
        reason: str = "invalid_json",
        validation_errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.reason = reason
        self.validation_errors = list(validation_errors or [])


class ContextWindowExceededError(LlmApiLabError):
    """拼好的消息超过模型上下文窗口（``input + reserved_output <= max_context``）。"""

    def __init__(
        self,
        estimated_tokens: int,
        available_input_tokens: int,
        *,
        model: str = "",
    ) -> None:
        super().__init__(
            f"context window exceeded for {model or 'model'}: "
            f"estimated {estimated_tokens} input tokens > "
            f"available {available_input_tokens}"
        )
        self.estimated_tokens = estimated_tokens
        self.available_input_tokens = available_input_tokens
        self.model = model
