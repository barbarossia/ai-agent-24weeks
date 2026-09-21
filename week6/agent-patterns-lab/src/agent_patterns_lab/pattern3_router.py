"""Pattern 3: Router / Dispatcher (路由与分流).

Applicability:
- Incoming queries belong to distinct categories/domains with specialized tools or specialist handlers.
- Fast, cost-effective intent classification before delegating to the right downstream branch.

Anti-pattern:
- Deep recursive routing trees; or routing when a single generalist agent with 2 tools can easily handle everything directly.
"""

from __future__ import annotations

import json
from typing import Dict

from .common import ExecutionTrace, HOMELAB_DATA


class NetworkSpecialist:
    def handle(self, query: str) -> str:
        net = HOMELAB_DATA["network"]
        return f"[NetworkSpecialist] Gateway: {net['gateway']}, DNS: {net['dns']}, OpenWrt: {net['openwrt_status']}, VPN: {net['vpn_status']}"


class DockerSpecialist:
    def handle(self, query: str) -> str:
        lines = []
        for host, containers in HOMELAB_DATA["containers"].items():
            names = ", ".join(f"{c['name']}({c['status']})" for c in containers)
            lines.append(f"{host}: {names}")
        return f"[DockerSpecialist] Container overview:\n  " + "\n  ".join(lines)


class HostSpecialist:
    def handle(self, query: str) -> str:
        lines = []
        for host, info in HOMELAB_DATA["hosts"].items():
            lines.append(f"{host}: status={info['status']}, cpu={info['cpu_percent']}%")
        return f"[HostSpecialist] Host hardware overview:\n  " + "\n  ".join(lines)


class RouterDispatcher:
    def __init__(self) -> None:
        self.specialists = {
            "network": NetworkSpecialist(),
            "docker": DockerSpecialist(),
            "host": HostSpecialist(),
        }

    def _route_intent(self, query: str) -> str:
        q = query.lower()
        if any(k in q for k in ["vpn", "dns", "gateway", "openwrt", "network", "route", "internet"]):
            return "network"
        if any(k in q for k in ["docker", "container", "nginx", "postgres", "redis"]):
            return "docker"
        if any(k in q for k in ["host", "hardware", "cpu", "server", "machine", "esxi"]):
            return "host"
        return "host"  # default fallback

    def run(self, query: str) -> ExecutionTrace:
        trace = ExecutionTrace(pattern_name="3. Router / Dispatcher", input_text=query)
        trace.log(f"Received user query: '{query}'")

        routed_domain = self._route_intent(query)
        trace.log(f"Router classified query intent as domain: '{routed_domain}'")

        specialist = self.specialists.get(routed_domain)
        if not specialist:
            trace.log(f"No specialist found for '{routed_domain}'")
            trace.output = f"Unknown domain {routed_domain}"
            return trace

        trace.log(f"Dispatching query to {specialist.__class__.__name__}")
        response = specialist.handle(query)
        trace.log(f"Specialist produced response.")
        trace.output = response
        return trace


def main() -> None:
    router = RouterDispatcher()
    queries = [
        "What is the status of OpenWrt and VPN connection?",
        "Are there any postgres or nginx containers running?",
        "Check overall CPU usage on all servers",
    ]
    print("=== Pattern 3: Router / Dispatcher ===")
    for q in queries:
        trace = router.run(q)
        print(f"\n[Input]: {trace.input_text}")
        for s in trace.steps:
            print(f"  -> {s}")
        print(f"[Output]:\n{trace.output}")


if __name__ == "__main__":
    main()
