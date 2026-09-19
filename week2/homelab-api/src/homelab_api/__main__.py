"""``python -m homelab_api`` / ``uv run homelab-api`` —— 启动 uvicorn。

默认 127.0.0.1:8000（仅本机可访问，不对外暴露）。
``--reload`` 适合开发；学习时改代码自动重启。
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

__all__ = ["main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab-api",
        description="启动 HomeLab API（Week 2 学习项目）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：代码变化自动重启",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    uvicorn.run(
        "homelab_api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - 直接 python -m 时使用
    raise SystemExit(main())
