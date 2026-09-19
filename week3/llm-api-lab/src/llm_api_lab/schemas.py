"""业务侧的结构化输出 schema：``User Question → LLM → Structured JSON → Pydantic``。

本文件同时演示"JSON Schema / Pydantic Schema"这一学习点：
- ``TriageResult.model_json_schema()`` 生成标准 JSON Schema，可直接放进
  ``response_format={"type": "json_schema", ...}`` 交给支持它的模型；
- 同时它又是**本地校验器**：无论模型怎么说"我保证是 JSON"，都要经过
  ``TriageResult.model_validate`` 才算数。

场景：HomeLab 告警分诊。模型把自然语言问题分类成
``category / severity / action``（Week 3 大纲要求的最小字段集）。
"""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import ResponseFormat

__all__ = [
    "TriageCategory",
    "Severity",
    "TriageResult",
    "INCIDENT_SYSTEM_PROMPT",
    "describe_schema",
    "json_response_format",
]


class TriageCategory(StrEnum):
    """问题所属领域。"""

    NETWORK = "network"
    STORAGE = "storage"
    COMPUTE = "compute"
    SECURITY = "security"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """严重程度。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class TriageResult(BaseModel):
    """模型必须产出的结构化结果。

    ``extra="forbid"`` 很关键：模型爱"贴心地"多返回字段，这里会直接拒绝，
    避免下游拿到未经定义的隐含契约。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: TriageCategory
    severity: Severity
    action: str = Field(min_length=1, max_length=120, description="建议的下一步动作")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=400, description="一句话理由")


INCIDENT_SYSTEM_PROMPT = (
    "你是一个 HomeLab 运维分诊助手。"
    "只输出一个 JSON 对象，不要输出 Markdown 代码块、解释或多余文字。"
    "字段：category(network|storage|compute|security|unknown)、"
    "severity(info|warning|critical)、action(简短英文动作)、"
    "confidence(0~1)、reason(一句话)。"
)


def describe_schema(schema: type[BaseModel]) -> str:
    """把 Pydantic 模型渲染成可放进提示词的 JSON Schema 文本。"""
    rendered = json.dumps(
        schema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"必须严格符合以下 JSON Schema：\n{rendered}"


def json_response_format(schema: type[BaseModel]) -> ResponseFormat:
    """构造 ``json_schema`` 形式的 response_format。"""
    return ResponseFormat.json_schema_of(
        schema.model_json_schema(),
        name=schema.__name__,
    )
