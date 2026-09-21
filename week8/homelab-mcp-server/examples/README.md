# Configuration Examples

This is a sanitized, placeholder JSON example. It does not contain real
credentials or a real HomeLab address. It is for local development/reference
only; real connectivity requires an explicit human-gated decision to point
`HOMELAB_MODE=openwrt` at your own infrastructure.

## `openwrt_config.example.json` — real OpenWrt router via ubus-over-HTTP

Use `OpenWrtAdapter` (`HOMELAB_MODE=openwrt`) to connect to an **actual**
OpenWrt router. This is a genuine implementation of OpenWrt's real, native
management protocol — **ubus-over-HTTP**, the same `/ubus` JSON-RPC 2.0
endpoint that LuCI itself uses — not a fictional REST API.

Protocol flow implemented by `OpenWrtAdapter`:

1. `POST /ubus` with ubus method `session.login` (anonymous session id
   `00000000000000000000000000000000`, plus `username`/`password`) to obtain
   a `ubus_rpc_session` id.
2. `POST /ubus` with the session id for each subsequent read-only call:
   `system.board` (device/hostname info), `system.info` (uptime, load,
   memory), `network.interface.dump` (interface list + up/down status),
   `network.device.status` (per-interface traffic counters).

Only this fixed set of read-only ubus calls is ever issued — see the
`_ALLOWED_UBUS_CALLS` allowlist in `openwrt_adapter.py`. No mutating ubus
calls (reboot, interface up/down, config commit, etc.) are implemented or
reachable. This does use HTTP `POST` at the transport level (ubus requires
it — OpenWrt has no GET-based equivalent), which is a deliberate, narrow,
allowlisted exception to this project's general GET-only default, documented
and scoped to exactly these 5 read-only ubus operations.

```powershell
$env:HOMELAB_MODE = "openwrt"
$env:OPENWRT_CONFIG_FILE = ".\examples\openwrt_config.example.json"
uv run homelab-mcp-demo
```

Requires ubus/rpcd HTTP access enabled on the router (enabled by default on
stock OpenWrt/LuCI installs) and valid `username`/`password` credentials for
a user allowed to call the object/methods above per `/usr/share/rpcd/acl.d/`.

> **Security boundary**: `OpenWrtAdapter` only ever calls the 5 allowlisted
> read-only ubus methods above; it never calls any mutating ubus method.
> Credentials are read from this JSON config only in memory, never logged or
> persisted, and the ubus session id is cached only for the adapter's
> lifetime. Placeholder credentials in this example file must be replaced
> with your own before use; do not commit real credentials to this
> repository.
