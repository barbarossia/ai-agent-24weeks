"""费用估算：token 用量 → 美元成本。

为什么单列一个文件？因为"成本"和"限流/重试"一样，是 LLM 应用**必须显式管理**的
运行约束：一次失控的重试可能把配额和钱烧光。

> 价格是**教学用示意值**，会随厂商调整。真实项目请以官方价目表为准，
> 并把价格表当作配置注入，而不是硬编码在业务逻辑里。
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from .models import Usage

__all__ = [
    "ModelPricing",
    "DEFAULT_PRICING",
    "pricing_for",
    "estimate_cost_usd",
]


class ModelPricing(BaseModel):
    """某模型的每 1K token 单价（美元）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_usd_per_1k: float = Field(ge=0)
    output_usd_per_1k: float = Field(ge=0)


# 示意价目表：mock 模型免费；其余为便于对比量级的近似值。
DEFAULT_PRICING: Mapping[str, ModelPricing] = {
    "mock-llm-v1": ModelPricing(input_usd_per_1k=0.0, output_usd_per_1k=0.0),
    "gpt-4o-mini": ModelPricing(input_usd_per_1k=0.00015, output_usd_per_1k=0.0006),
    "gpt-4o": ModelPricing(input_usd_per_1k=0.0025, output_usd_per_1k=0.01),
    "claude-3-5-sonnet": ModelPricing(
        input_usd_per_1k=0.003, output_usd_per_1k=0.015
    ),
}


def pricing_for(
    model: str,
    table: Mapping[str, ModelPricing] = DEFAULT_PRICING,
) -> ModelPricing:
    """查价格；未知模型按 0 计（避免因缺价格表而崩溃，但会显式返回 0）。"""
    return table.get(model, ModelPricing(input_usd_per_1k=0.0, output_usd_per_1k=0.0))


def estimate_cost_usd(
    usage: Usage,
    pricing: ModelPricing,
) -> float:
    """按用量估算成本（美元）。注意输出 token 通常比输入贵 3~5 倍。"""
    return (
        usage.prompt_tokens / 1000.0 * pricing.input_usd_per_1k
        + usage.completion_tokens / 1000.0 * pricing.output_usd_per_1k
    )
