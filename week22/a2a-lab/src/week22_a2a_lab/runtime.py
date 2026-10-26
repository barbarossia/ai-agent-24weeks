"""Start two independent A2A services for a local demo or integration test."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


LAB_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


class AgentServices:
    """Own and stop two local subprocesses: coordinator and specialist."""

    def __init__(self, startup_timeout_seconds: float = 5.0):
        self.startup_timeout_seconds = startup_timeout_seconds
        self.specialist_url = f"http://127.0.0.1:{_free_port()}"
        self.coordinator_url = f"http://127.0.0.1:{_free_port()}"
        self._processes: list[subprocess.Popen[bytes]] = []

    def __enter__(self) -> AgentServices:
        try:
            specialist_port = int(self.specialist_url.rsplit(":", 1)[1])
            coordinator_port = int(self.coordinator_url.rsplit(":", 1)[1])
            self._processes.append(self._start("specialist", specialist_port))
            self._wait_for_card(self.specialist_url, "specialist")
            self._processes.append(self._start(
                "coordinator", coordinator_port, specialist_url=self.specialist_url
            ))
            self._wait_for_card(self.coordinator_url, "coordinator")
            return self
        except BaseException:
            self._stop()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop()

    def _stop(self) -> None:
        for process in reversed(self._processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._processes.clear()

    def _start(
        self, role: str, port: int, *, specialist_url: str | None = None
    ) -> subprocess.Popen[bytes]:
        command = [
            sys.executable,
            "-m",
            "week22_a2a_lab.server",
            "--role",
            role,
            "--port",
            str(port),
        ]
        if specialist_url:
            command.extend(["--specialist-url", specialist_url])
        return subprocess.Popen(
            command,
            cwd=LAB_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    def _wait_for_card(self, base_url: str, role: str) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            process = next((p for p in self._processes if p.poll() is not None), None)
            if process:
                raise RuntimeError(f"{role} service exited during startup: {process.returncode}")
            try:
                response = httpx.get(
                    f"{base_url}/.well-known/agent-card.json",
                    timeout=0.1,
                    trust_env=False,
                )
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.02)
        raise TimeoutError(f"{role} service did not publish its Agent Card")
