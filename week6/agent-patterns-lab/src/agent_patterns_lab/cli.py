"""CLI runner executing all 4 architectural patterns or targeted individual patterns."""

from __future__ import annotations

import sys
from .pattern1_single_tool import SingleAgentWithTools
from .pattern2_pipeline import SequentialPipeline
from .pattern3_router import RouterDispatcher
from .pattern4_supervisor import SupervisorAgent


def run_all() -> None:
    print("=" * 60)
    print("Agent Patterns Lab: Running all 4 architectural patterns")
    print("=" * 60)

    # 1. Single Agent with Tools
    print("\n" + "-" * 50)
    print("Pattern 1: Single Agent with Tools")
    print("-" * 50)
    agent1 = SingleAgentWithTools()
    t1 = agent1.run("Check status of host web01")
    for s in t1.steps:
        print(f"  {s}")
    print(f"Result: {t1.output}")

    # 2. Sequential Pipeline
    print("\n" + "-" * 50)
    print("Pattern 2: Sequential Pipeline")
    print("-" * 50)
    pipeline = SequentialPipeline()
    t2 = pipeline.run("db01")
    for s in t2.steps:
        print(f"  {s}")
    print(f"Result:\n{t2.output}")

    # 3. Router / Dispatcher
    print("\n" + "-" * 50)
    print("Pattern 3: Router / Dispatcher")
    print("-" * 50)
    router = RouterDispatcher()
    t3 = router.run("Show active docker containers on db01")
    for s in t3.steps:
        print(f"  {s}")
    print(f"Result:\n{t3.output}")

    # 4. Supervisor-Worker
    print("\n" + "-" * 50)
    print("Pattern 4: Supervisor-Worker")
    print("-" * 50)
    supervisor = SupervisorAgent()
    t4 = supervisor.run(["web01", "esxi01"])
    for s in t4.steps:
        print(f"  {s}")
    print(f"Result:\n{t4.output}")

    print("\n" + "=" * 60)
    print("All 4 patterns executed successfully!")
    print("=" * 60)


def main() -> None:
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if "1" in arg or "single" in arg:
            from .pattern1_single_tool import main as m1
            m1()
            return
        if "2" in arg or "pipeline" in arg:
            from .pattern2_pipeline import main as m2
            m2()
            return
        if "3" in arg or "router" in arg:
            from .pattern3_router import main as m3
            m3()
            return
        if "4" in arg or "supervisor" in arg:
            from .pattern4_supervisor import main as m4
            m4()
            return

    run_all()


if __name__ == "__main__":
    main()
