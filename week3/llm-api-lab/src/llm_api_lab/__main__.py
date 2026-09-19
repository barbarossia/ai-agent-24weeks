"""``python -m llm_api_lab`` / ``uv run llm-api-lab`` 入口。"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover - 直接 python -m 时使用
    raise SystemExit(main())
