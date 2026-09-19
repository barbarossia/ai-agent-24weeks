"""消息模型、token 估算与上下文窗口的测试（成功 + 边界）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_api_lab.errors import ContextWindowExceededError
from llm_api_lab.messages import (
    ContextWindow,
    Conversation,
    Message,
    Role,
    estimate_tokens,
)


def test_role_values_are_wire_strings() -> None:
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_message_rejects_blank_content() -> None:
    with pytest.raises(ValidationError):
        Message(role=Role.USER, content="   ")


def test_message_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Message(role=Role.USER, content="hi", unexpected=True)  # type: ignore[call-arg]


def test_conversation_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        Conversation(messages=[])


def test_system_message_must_be_first() -> None:
    with pytest.raises(ValidationError):
        Conversation(
            messages=[
                Message(role=Role.USER, content="hi"),
                Message(role=Role.SYSTEM, content="late"),
            ]
        )


def test_only_one_system_message_allowed() -> None:
    with pytest.raises(ValidationError):
        Conversation(
            messages=[
                Message(role=Role.SYSTEM, content="a"),
                Message(role=Role.SYSTEM, content="b"),
                Message(role=Role.USER, content="hi"),
            ]
        )


def test_last_message_must_not_be_system() -> None:
    with pytest.raises(ValidationError):
        Conversation(messages=[Message(role=Role.SYSTEM, content="only system")])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   ", 0),
        ("abcd", 1),  # 4 ASCII chars -> 1
        ("network down", 3),  # 12 chars -> ceil(12/4) = 3
        ("网络", 2),  # 2 CJK chars -> 2
    ],
)
def test_estimate_tokens(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected


def test_estimate_tokens_counts_mixed_text() -> None:
    # 8 ASCII + 2 CJK -> ceil(8/4) + 2 = 4
    assert estimate_tokens("abcdefgh网络") == 4


def test_conversation_estimated_tokens_includes_overhead(conversation: Conversation) -> None:
    # 每条消息 +4 的固定开销
    expected = sum(estimate_tokens(m.content) + 4 for m in conversation.messages)
    assert conversation.estimated_tokens == expected


def test_with_message_is_immutable_append() -> None:
    base = Conversation(messages=[Message(role=Role.USER, content="hi")])
    extended = base.with_message(Message(role=Role.ASSISTANT, content="hello"))
    assert len(base.messages) == 1
    assert len(extended.messages) == 2
    assert extended.messages[-1].role is Role.ASSISTANT


def test_context_window_available_tokens() -> None:
    window = ContextWindow(max_context_tokens=1000, reserved_output_tokens=200)
    assert window.available_input_tokens == 800


def test_context_window_never_negative() -> None:
    window = ContextWindow(max_context_tokens=100, reserved_output_tokens=500)
    assert window.available_input_tokens == 0


def test_context_window_allows_small_conversation(conversation: Conversation) -> None:
    window = ContextWindow(max_context_tokens=4096, reserved_output_tokens=512)
    estimated = window.ensure_fits(conversation, model="mock-llm-v1")
    assert estimated == conversation.estimated_tokens


def test_context_window_rejects_oversized_conversation() -> None:
    huge = Conversation(
        messages=[
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="网络抖动 " * 200),
        ]
    )
    window = ContextWindow(max_context_tokens=64, reserved_output_tokens=16)
    with pytest.raises(ContextWindowExceededError) as excinfo:
        window.ensure_fits(huge, model="mock-llm-v1")
    assert excinfo.value.model == "mock-llm-v1"
    assert excinfo.value.available_input_tokens == 48
    assert excinfo.value.estimated_tokens > 48
