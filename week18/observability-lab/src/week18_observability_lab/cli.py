"""CLI for offline observability scenarios."""
import argparse
import json
import sys
from .demo import DemoAgent

def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline Week 18 observability demo")
    parser.add_argument("--fault", choices=("none", "slow", "failure", "retry"), default="none")
    parser.add_argument("--format", choices=("summary", "json", "prometheus"), default="summary")
    args = parser.parse_args(argv)
    agent = DemoAgent()
    try:
        result = agent.handle(fault=args.fault)
        code = 0
    except RuntimeError:
        result = {"status": "error", "fault": args.fault, "span_count": len(agent.tracer.spans)}
        code = 1
    if args.format == "prometheus": print(agent.metrics.render(), end="")
    elif args.format == "json": print(json.dumps({**result, "spans": [s.to_dict() for s in agent.tracer.spans]}, sort_keys=True))
    else: print(f"status={result['status']} fault={args.fault} spans={result['span_count']} synthetic_latency_ms={result.get('synthetic_latency_ms', 3)}")
    return code

if __name__ == "__main__":
    sys.exit(main())
