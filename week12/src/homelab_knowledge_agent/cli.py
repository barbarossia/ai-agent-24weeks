import argparse
import asyncio
import sys

from .agent import KnowledgeAgent
from .errors import IntegrationBlocked
from .generation import CodexGeneration
from .homelab import MockHomeLab
from .rag import Week11Retrieval


def parser():
    root = argparse.ArgumentParser(description="Read-only Week 11 RAG + Week 8 MockAdapter + Codex App Server")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("auth-status", help="Check managed ChatGPT auth without displaying account details")
    ask = commands.add_parser("ask", help="Synthesize one question using RAG and current-request mock MCP data")
    ask.add_argument("question")
    ask.add_argument("--model", required=True, help="An OpenAI model available to your ChatGPT-managed Codex account")
    ask.add_argument("--top-k", type=int, choices=range(1, 6), default=3)
    ask.add_argument("--source-path", help="Exact existing sanitized Week 11 source identity")
    ask.add_argument("--tag", action="append", default=[], help="Exact tag; repeated values use ANY")
    return root


def build_agent(args):
    return KnowledgeAgent(Week11Retrieval(args.top_k, args.source_path, args.tag),
                          MockHomeLab(), CodexGeneration(args.model))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "auth-status":
            print(asyncio.run(CodexGeneration(None).check_auth()))
        else:
            print(asyncio.run(build_agent(args).answer(args.question)))
        return 0
    except IntegrationBlocked as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Raw driver/model/subprocess errors can contain credentials or private evidence.
        print("Operation failed; verify input, local dependencies and supported integration configuration.", file=sys.stderr)
        return 1
