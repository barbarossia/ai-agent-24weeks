"""Shared constants for the Week 17 evaluation lab."""

SCHEMA_VERSION = "1"

# Fixed-contract disclaimer (H001 §D3 / H003 §5). Written verbatim into the
# README and the report header. Week 17 must never claim dynamic tool selection.
DISCLAIMER = (
    "The evaluated agent performs a fixed ping->get_health_status sequence coded in Week 12; "
    "no component selects tools or arguments per question. Week 17 therefore measures "
    "integration-allowlist conformance and argument-shape accuracy (empty {}), "
    "NOT dynamic per-question tool selection."
)

# Verbatim manual-Judge provenance statement (H003 §5 / correction-verification §6).
JUDGE_PROVENANCE_SHORT = (
    "示例判定为用户提供的样例（仅验证 Judge schema 与流程），本轮未调用任何模型；"
    "Judge 路径与确定性离线评测分离，离线指标不依赖 Judge。"
)
