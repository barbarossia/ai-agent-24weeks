"""URL constraints that keep this lab's HTTP traffic on loopback."""
from __future__ import annotations

from urllib.parse import urlsplit


def require_loopback_http_url(url: str) -> str:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("this lab only connects to HTTP services on 127.0.0.1")
    return f"http://127.0.0.1:{port}"
