# Docker Compose verification

Verified on 2026-10-26 from this lab directory with the current source and lockfile:

```text
docker compose config --quiet       PASS
docker compose build lab            PASS
docker compose run --rm lab eval    PASS: 3 recovery cases, pause and rejection gates passed
```

The Compose service uses `network_mode: none`, `read_only: true`, user `65532:65532`, `cap_drop: [ALL]`, `no-new-privileges`, and a bounded `/tmp` tmpfs. Its only general writable volume is `/data`, used for SQLite checkpoints and local run outputs. A named `/app/vault/knowledge/reports` volume is reserved for the separately confirmed optional report export.

The container eval reproduced the host checks: three cited cause-to-recovery cases, an observed approval interrupt for each approved run, separate pause and rejection gates with zero write calls, reports, and no capability in traces.
