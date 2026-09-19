"""示例 1：User Question → LLM → Structured JSON → Pydantic Validation。

运行：``uv run python examples/01_structured_triage.py``

不联网：使用确定性的 ``MockProvider``。真实模型也会返回**字符串**，
所以这里的"解析 + 校验"两步在任何 provider 下都不可省略。
"""

from __future__ import annotations

import asyncio

from llm_api_lab.client import LLMClient
from llm_api_lab.messages import Conversation, Message, Role
from llm_api_lab.models import ModelConfig
from llm_api_lab.providers import MockProvider
from llm_api_lab.schemas import INCIDENT_SYSTEM_PROMPT, TriageResult, describe_schema


def build_conversation(question: str) -> Conversation:
    system = f"{INCIDENT_SYSTEM_PROMPT}\n\n{describe_schema(TriageResult)}"
    return Conversation(
        messages=[
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=question),
        ]
    )


async def main() -> int:
    question = "NAS 磁盘快满了，服务很慢，怎么办？"
    provider = MockProvider()
    client = LLMClient(provider, config=ModelConfig(model="mock-llm-v1"))

    result = await client.complete_structured(build_conversation(question), TriageResult)

    print(f"Q            : {question}")
    print(f"model raw    : {result.completion.text}")
    print(f"validated    : {result.value.model_dump_json(ensure_ascii=False)}")
    print(f"category     : {result.value.category}")
    print(f"severity     : {result.value.severity}")
    print(f"action       : {result.value.action}")
    print(f"usage        : {result.completion.usage.model_dump()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
