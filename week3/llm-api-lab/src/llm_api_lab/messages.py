"""消息模型与上下文预算：LLM API 的"输入"到底是什么。

三条主线：
1. **Message roles**：``system`` 设定行为，``user`` 提问，``assistant`` 是模型历史回复，
   ``tool`` 是工具结果（Week 4 才真正用）。角色顺序有约束（system 只能最前）。
2. **Token / Context Window**：模型按 token 计费、按 token 限长。这里用一个
   **可解释的近似估算器**（不是真实 tokenizer），把"上下文预算"这件事显式化。
3. **输入校验**：消息来自用户 / 代码 / 历史记录，属于外部边界 → 必须用 Pydantic 校验。

> 近似估算：英文约 4 字符 1 token，中日韩字符约 1 字符 1 token。
> 真实计费请用官方 tokenizer（如 ``tiktoken``）——本估算只用于教学与预算演示，
> 刻意不引入额外依赖，也**不应用于精确计费**。
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ContextWindowExceededError

__all__ = [
    "Role",
    "Message",
    "Conversation",
    "ContextWindow",
    "estimate_tokens",
]


class Role(StrEnum):
    """聊天角色。``StrEnum`` 让成员本身就是字符串，可直接进 JSON。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """一条聊天消息（外部/内部边界模型）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    content: str = Field(description="消息正文；不允许空白-only")

    @field_validator("content")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """拒绝空白-only 内容：这类消息对模型无意义，多半是拼装 bug。"""
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value


class Conversation(BaseModel):
    """一轮待发送给模型的消息序列。

    校验规则（把"API 契约"显式化，错误在构造时就暴露）：
    - 至少 1 条消息；
    - ``system`` 只能出现在第 0 条，且最多 1 条；
    - 最后一条不能是 ``system``（否则模型没有可回复的输入）。
    """

    model_config = ConfigDict(frozen=True)

    messages: list[Message] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_ordering(self) -> Conversation:
        system_indexes = [i for i, m in enumerate(self.messages) if m.role is Role.SYSTEM]
        if len(system_indexes) > 1:
            raise ValueError("at most one system message is allowed")
        if system_indexes and system_indexes[0] != 0:
            raise ValueError("system message must be first")
        if self.messages[-1].role is Role.SYSTEM:
            raise ValueError("last message must not be a system message")
        return self

    @property
    def estimated_tokens(self) -> int:
        """整段对话的近似输入 token 数（每条消息额外 +4，模拟角色/分隔开销）。"""
        return sum(estimate_tokens(m.content) + 4 for m in self.messages)

    def with_message(self, message: Message) -> Conversation:
        """返回追加一条消息后的新对话（不可变，避免共享状态被就地改写）。"""
        return Conversation(messages=[*self.messages, message])


def estimate_tokens(text: str) -> int:
    """近似估算文本的 token 数。

    规则（刻意简单、可解释、跨语言可预测）：
    - 空白-only 或空串 → 0；
    - 非 ASCII 字符（CJK 等）按 1 字符 ≈ 1 token；
    - ASCII 字符按 4 字符 ≈ 1 token。

    这不是精确值。它存在的意义是让"上下文预算"在代码里**可计算、可测试**。
    """
    if not text or not text.strip():
        return 0
    ascii_count = sum(1 for ch in text if ch.isascii())
    non_ascii_count = len(text) - ascii_count
    return max(1, math.ceil(ascii_count / 4) + non_ascii_count)


class ContextWindow(BaseModel):
    """模型的上下文预算。

    ``available_input_tokens = max_context_tokens - reserved_output_tokens``；
    拼好的输入超过它就应该**提前拒绝**，而不是把请求发出去等 400。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_context_tokens: int = Field(ge=1, description="模型总上下文窗口")
    reserved_output_tokens: int = Field(
        default=512,
        ge=0,
        description="为模型输出预留的 token，不计入输入预算",
    )

    @property
    def available_input_tokens(self) -> int:
        return max(0, self.max_context_tokens - self.reserved_output_tokens)

    def ensure_fits(self, conversation: Conversation, *, model: str = "") -> int:
        """校验对话是否放得下，返回估算的输入 token 数。

        超限抛 ``ContextWindowExceededError``（携带结构化字段），
        让调用方可以据此裁剪历史或拒绝请求。
        """
        estimated = conversation.estimated_tokens
        if estimated > self.available_input_tokens:
            raise ContextWindowExceededError(
                estimated_tokens=estimated,
                available_input_tokens=self.available_input_tokens,
                model=model,
            )
        return estimated
