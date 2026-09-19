"""模型 API 的**线缆层**模型（wire models）+ 模型配置。

这一层刻意模仿 OpenAI 兼容 ``/v1/chat/completions`` 的形状，但不绑定任何厂商：
它描述的是"请求发出去长什么样、响应回来长什么样"。好处是：
- mock provider 与真实 HTTP provider 返回**同一种结构**，上层无需分支；
- 响应解析（response parsing）成为一次显式的 Pydantic 校验，而不是随手取字典键。

模型配置（``ModelConfig``）把 temperature / max_output_tokens / timeout 等
"调用策略"集中到一处，避免散落在业务代码里。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .messages import Message

__all__ = [
    "ReasoningEffort",
    "ModelConfig",
    "ResponseFormat",
    "ChatRequest",
    "Usage",
    "ChatResponse",
    "StreamChunk",
]

ReasoningEffort = Literal["low", "medium", "high"]


class ModelConfig(BaseModel):
    """一次会话使用的模型与采样参数。

    ``timeout_s=None`` 表示不限时（不建议用于生产）。
    ``reasoning_effort`` 是"推理强度"配置示例：真实厂商用它控制思维链预算，
    mock provider 会忽略它（这正是 mock 与真实的差异之一）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(default="mock-llm-v1", min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=512, ge=1)
    timeout_s: float | None = Field(default=10.0, gt=0)
    reasoning_effort: ReasoningEffort | None = None
    stop: tuple[str, ...] = ()


class ResponseFormat(BaseModel):
    """约束模型输出格式。

    - ``text``：普通文本；
    - ``json_object``：要求输出是合法 JSON（但不保证符合你的 schema）；
    - ``json_schema``：同时给出 JSON Schema（最强约束，厂商支持度不一）。

    Week 3 的结论：**即使厂商支持 json_schema，仍要在本地用 Pydantic 校验一次**
    —— 模型输出永远属于不可信输入。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["text", "json_object", "json_schema"] = "text"
    json_schema: dict[str, Any] | None = None

    @classmethod
    def json_object(cls) -> ResponseFormat:
        return cls(type="json_object")

    @classmethod
    def json_schema_of(cls, schema: dict[str, Any], *, name: str) -> ResponseFormat:
        return cls(
            type="json_schema",
            json_schema={"name": name, "schema": schema, "strict": True},
        )


class ChatRequest(BaseModel):
    """发往 provider 的请求（线缆层）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    messages: tuple[Message, ...] = Field(min_length=1)
    temperature: float = 0.0
    max_output_tokens: int = 512
    response_format: ResponseFormat = Field(default_factory=ResponseFormat)
    stream: bool = False
    stop: tuple[str, ...] = ()


class Usage(BaseModel):
    """token 用量。``total_tokens`` 由前后两者推导，避免三处不一致。"""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatResponse(BaseModel):
    """provider 返回的一次完整回复（非流式）。

    ``reasoning`` 对应部分推理模型的思维链字段（可能为空）；本项目仅做透传与展示。
    """

    model_config = ConfigDict(frozen=True)

    id: str
    model: str
    content: str
    finish_reason: str = "stop"
    usage: Usage
    reasoning: str | None = None


class StreamChunk(BaseModel):
    """流式响应的一小片。

    ``delta`` 是本片的增量文本；``finish_reason`` 只在最后一片出现；
    ``usage`` 也通常只在最后一片返回（取决于厂商）。
    """

    model_config = ConfigDict(frozen=True)

    delta: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None
