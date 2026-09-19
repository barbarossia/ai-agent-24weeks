"""命令行入口：参数解析 + 输出渲染。

设计要点：
- 业务逻辑全部在 ``service``，这里只做 I/O 与错误→退出码的映射。
- ``main`` 返回 int（退出码），方便被测试直接调用，也方便脚本化。
- 退出码约定（类似 Linux 工具）：
    0 = 成功且健康
    1 = 检查完成但存在 DOWN（CI 可用它判断失败）
    2 = 输入/数据错误（清单非法、主机不存在）
    3 = 检查执行失败
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .errors import AiAgentLabError, CheckFailedError, HostNotFoundError, InventoryError
from .models import CheckResult, HealthStatus, Inventory
from .service import check_all, check_host, default_inventory, load_inventory, summarize

__all__ = ["build_parser", "main"]

# ANSI 颜色；非 TTY 时也不会出错，只是失去颜色。
_COLORS = {
    HealthStatus.UP: "\033[32m",       # green
    HealthStatus.DEGRADED: "\033[33m",  # yellow
    HealthStatus.DOWN: "\033[31m",      # red
    HealthStatus.UNKNOWN: "\033[90m",   # grey
}
_RESET = "\033[0m"


def build_parser() -> argparse.ArgumentParser:
    """构建 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="ai-agent-lab",
        description="HomeLab 主机状态检查 CLI（Week 1 学习项目）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-i",
        "--inventory",
        type=Path,
        default=None,
        help="主机清单 JSON 路径；缺省使用内置示例清单",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="以 JSON 输出，便于脚本/后续 Agent 消费",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出清单中的所有主机")

    check = sub.add_parser("check", help="检查单台主机")
    check.add_argument("hostname", help="主机名（清单中的 name）")

    sub.add_parser("check-all", help="检查所有主机并输出汇总")

    return parser


def _load_inventory(path: Path | None) -> Inventory:
    """按参数加载清单；未指定路径时用内置示例。"""
    if path is None:
        return default_inventory()
    return load_inventory(path)


def _colorize(status: HealthStatus, text: str) -> str:
    return f"{_COLORS.get(status, '')}{text}{_RESET}"


def _render_table(results: Sequence[CheckResult]) -> str:
    """渲染对齐的文本表格。"""
    header = f"{'HOST':<14}{'KIND':<10}{'STATUS':<12}{'LATENCY':>9}  MESSAGE"
    lines = [header, "-" * len(header)]
    for result in results:
        status = _colorize(result.status, result.status.value.upper())
        # 注意：颜色转义码会占宽度，表格对齐按纯文本宽度手算。
        pad = " " * max(0, 12 - len(result.status.value.upper()))
        lines.append(
            f"{result.host.name:<14}{result.host.kind.value:<10}"
            f"{status}{pad}{result.latency_ms:>7}ms  {result.message}"
        )
    return "\n".join(lines)


def _render_json(results: Sequence[CheckResult]) -> str:
    summary = summarize(results)
    payload = {
        "results": [result.model_dump(mode="json") for result in results],
        "summary": summary.as_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _exit_code_for(results: Sequence[CheckResult]) -> int:
    """存在 DOWN 时返回 1，否则 0。"""
    return 1 if any(r.status is HealthStatus.DOWN for r in results) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主函数。返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        inventory = _load_inventory(args.inventory)

        if args.command == "list":
            if args.as_json:
                print(json.dumps([h.model_dump(mode="json") for h in inventory.hosts],
                                 ensure_ascii=False, indent=2))
            else:
                for host in inventory.hosts:
                    tags = ",".join(host.tags) or "-"
                    print(f"{host.name:<14}{host.kind.value:<10}{host.address:<18}{tags}")
            return 0

        if args.command == "check":
            host = inventory.find(args.hostname)
            if host is None:
                raise HostNotFoundError(args.hostname)
            results = [check_host(host)]
        else:  # check-all
            results = check_all(inventory)

        if args.as_json:
            print(_render_json(results))
        else:
            print(_render_table(results))
            summary = summarize(results)
            verdict = "HEALTHY" if summary.healthy else "ATTENTION"
            print(
                f"\nsummary: {summary.up} up, {summary.degraded} degraded, "
                f"{summary.down} down, {summary.unknown} unknown "
                f"=> {verdict}"
            )
        return _exit_code_for(results)

    except HostNotFoundError as exc:
        print(f"error: {exc.hostname!r} not found in inventory", file=sys.stderr)
        return 2
    except InventoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CheckFailedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except AiAgentLabError as exc:  # 兜底：任何领域异常都不应变成 traceback
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - 直接 python cli.py 时使用
    raise SystemExit(main())
