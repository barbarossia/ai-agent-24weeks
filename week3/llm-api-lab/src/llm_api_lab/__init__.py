"""llm-api-lab —— Week 3（LLM API Fundamentals）学习项目。

目标：不依赖任何 Agent Framework，直接理解模型 API 的输入、输出与约束：
消息角色、token / 上下文窗口、结构化输出（JSON Schema + Pydantic 校验）、
streaming、超时/重试，以及安全边界。

默认全部走进程内 mock，**无需 API key、不访问网络、不产生费用**。
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
