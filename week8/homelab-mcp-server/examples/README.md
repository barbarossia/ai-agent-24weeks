# RealAdapter Configuration Examples

These are sanitized, placeholder JSON examples for `RealAdapterConfig`.
None of them contain real credentials or real HomeLab addresses. They are
for local development/reference only; real connectivity requires an explicit
human-gated decision to point `HOMELAB_MODE=real` at your own infrastructure.

## `real_adapter_config.example.json`

Generic example using the default REST path templates
(`/api/v1/inventory`, `/api/v1/health[/{target_id}]`, `/api/v1/metrics/{target_id}`).
Use this if your real backend already exposes a unified REST API in that shape
(e.g. a custom monitoring service or gateway you control).

```bash
$env:HOMELAB_MODE = "real"
$env:HOMELAB_CONFIG_FILE = ".\examples\real_adapter_config.example.json"
uv run homelab-mcp-demo
```

## `openwrt_config.example.json`

Example targeting a bare IP (`192.168.1.1`, auto-normalized to `http://192.168.1.1`)
with custom path templates, for the realistic case where a device like OpenWrt
does **not** natively expose `/api/v1/...` REST endpoints.

OpenWrt's native status interface is **ubus-over-HTTP** (`/ubus`, JSON-RPC 2.0),
which requires a session-authenticated `POST` login followed by `POST` calls
(e.g. `ubus call system board`, `ubus call system info`). That POST/JSON-RPC
flow is intentionally **not implemented** in this project, because it conflicts
with the strict read-only, GET-only security boundary that was reviewed and
approved for this HomeLab MCP Server.

> ⚠️ **`/cgi-bin/exporter/...` is NOT a real OpenWrt path.** It is a fictional
> placeholder representing "assume you wrote and deployed your own exporter
> script at this path." OpenWrt does **not** ship with any `/api/v1/...` or
> `/cgi-bin/exporter/...`-style read-only REST/GET API out of the box. To
> actually connect this project to a real OpenWrt router, you must write and
> deploy that exporter script yourself (it internally converts to ubus
> POST/JSON-RPC calls, and only exposes GET routes externally), then update
> these fields to match your exporter's real routes.

To connect this project to a real OpenWrt router (or any similar device) while
preserving that GET-only boundary, deploy your own small read-only exporter/
gateway script on or near the device — it internally performs whatever
POST/JSON-RPC calls are needed against ubus, and exposes only simple GET
endpoints externally. Then point the `*_path`/`*_path_template` fields at that
exporter's routes, as shown in this example (`/cgi-bin/exporter/...` is a
placeholder path — replace it with your exporter's actual routes).

```bash
$env:HOMELAB_MODE = "real"
$env:HOMELAB_CONFIG_FILE = ".\examples\openwrt_config.example.json"
uv run homelab-mcp-demo
```

> **Security boundary**: This repository never issues HTTP `POST`/mutating
> requests, and does not implement ubus/JSON-RPC. Deploying and securing any
> exporter/gateway in front of a real device is entirely your own
> responsibility and is out of scope for this repository.
