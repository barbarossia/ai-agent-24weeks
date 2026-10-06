# Week 19: Agent Security Lab

A standard-library, offline demonstration of a defensive agent tool boundary. The lab treats retrieved text as untrusted data, validates tool arguments, checks a narrow permission policy, requires explicit approval for consequential actions, and gives tools only the minimum context they need.

## Run

From this directory:

```sh
python3 -m src.agent_security_lab
```

The deterministic scenarios exercise prompt injection, indirect injection in retrieved content, tool poisoning, data exfiltration, SSRF, secret leakage, RAG poisoning, excessive agency, and a permitted read. The demo makes no network calls and uses synthetic inputs only.

## Security model

The pipeline is `untrusted input → policy decision → permission check → argument validation → approval gate → tool`. Policy is code-owned; content cannot amend it. Read and write capabilities are distinct. URL checks accept only HTTPS URLs on an explicit host allow-list and reject local/private destinations and credential-bearing URLs. Secret values are never included in tool context or decision output. Write actions require approval; the demo has no real write tool.

These controls demonstrate layering, not a complete prompt-injection solution. Real deployments must enforce boundaries outside the model, use robust URL resolution and egress controls, protect approval UX, and audit tool implementations.
