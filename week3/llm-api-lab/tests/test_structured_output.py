"""结构化输出：JSON 提取、Pydantic 校验、修复重试的测试。"""

from __future__ import annotations

import pytest

from llm_api_lab.client import LLMClient, RetryPolicy, extract_json, parse_structured
from llm_api_lab.errors import StructuredOutputError
from llm_api_lab.messages import Conversation
from llm_api_lab.models import ModelConfig
from llm_api_lab.providers import MockProvider, Script, ScriptedProvider
from llm_api_lab.schemas import TriageResult, json_response_format

VALID = '{"category":"storage","severity":"warning","action":"clean_disk"}'


# --------------------------------------------------------------------------- #
# extract_json（宽容提取）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (VALID, VALID),
        (f"```json\n{VALID}\n```", VALID),
        (f"好的，结果如下：\n{VALID}\n希望有帮助", VALID),
    ],
)
def test_extract_json_variants(raw: str, expected: str) -> None:
    assert extract_json(raw) == expected


def test_extract_json_returns_input_when_no_object() -> None:
    assert extract_json("plain text") == "plain text"


# --------------------------------------------------------------------------- #
# parse_structured（校验）
# --------------------------------------------------------------------------- #
def test_parse_structured_success() -> None:
    result = parse_structured(VALID, TriageResult)
    assert result.category == "storage"
    assert result.severity == "warning"


def test_parse_invalid_json_raises_with_raw_text() -> None:
    with pytest.raises(StructuredOutputError) as excinfo:
        parse_structured('{"category": "storage"', TriageResult)
    assert excinfo.value.reason == "invalid_json"
    assert excinfo.value.raw_text == '{"category": "storage"'


def test_parse_schema_mismatch_raises_with_details() -> None:
    bad = '{"category":"storage","severity":"very-bad","action":"x"}'
    with pytest.raises(StructuredOutputError) as excinfo:
        parse_structured(bad, TriageResult)
    assert excinfo.value.reason == "schema_mismatch"
    assert excinfo.value.validation_errors


def test_parse_rejects_extra_field() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured(f'{{"category":"storage","severity":"info","action":"x","oops":1}}', TriageResult)


# --------------------------------------------------------------------------- #
# complete_structured（端到端）
# --------------------------------------------------------------------------- #
async def test_complete_structured_happy_path(
    conversation: Conversation, mock_provider: MockProvider
) -> None:
    client = LLMClient(mock_provider, config=ModelConfig(model="mock-llm-v1"))
    result = await client.complete_structured(conversation, TriageResult)

    assert result.repairs == 0
    assert result.completion.attempts == 1
    assert result.value.category == "storage"
    # 确认确实把 json_schema 约束传给了 provider（模型侧约束）
    assert mock_provider.calls[0].response_format.type == "json_schema"


async def test_complete_structured_repairs_invalid_json(
    conversation: Conversation,
) -> None:
    provider = ScriptedProvider(
        scripts=[Script(text='{"category": "storage"'), Script(text=VALID)]
    )
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    result = await client.complete_structured(
        conversation, TriageResult, repair_attempts=1
    )

    assert result.repairs == 1
    assert result.value.category == "storage"
    assert len(provider.calls) == 2
    # 修复过程的消息更长，且用量被累加（修复也要花钱）
    assert result.completion.usage.prompt_tokens > 0
    assert len(provider.calls[1].messages) == len(conversation.messages) + 2


async def test_complete_structured_raises_when_repairs_exhausted(
    conversation: Conversation,
) -> None:
    provider = ScriptedProvider(
        scripts=[Script(text='{"bad"'), Script(text='{"still": "bad"}')]
    )
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    with pytest.raises(StructuredOutputError) as excinfo:
        await client.complete_structured(conversation, TriageResult, repair_attempts=1)
    assert excinfo.value.reason in {"invalid_json", "schema_mismatch"}
    assert len(provider.calls) == 2


async def test_repair_disabled_fails_fast(conversation: Conversation) -> None:
    provider = ScriptedProvider(scripts=[Script(text='{"bad"'), Script(text=VALID)])
    client = LLMClient(provider, retry=RetryPolicy(max_attempts=1))
    with pytest.raises(StructuredOutputError):
        await client.complete_structured(conversation, TriageResult, repair_attempts=0)
    assert len(provider.calls) == 1


def test_json_response_format_shape() -> None:
    fmt = json_response_format(TriageResult)
    assert fmt.type == "json_schema"
    assert fmt.json_schema is not None
    assert fmt.json_schema["name"] == "TriageResult"
    assert "properties" in fmt.json_schema["schema"]
