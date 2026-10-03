# Week 16 H006 verification evidence

Generated 2026-10-03. Test subprocesses use the existing Week 15 Python 3.12.13 environment with the locked LangGraph stack; tracing is disabled and tests install a socket-failing offline guard. CLI demos use temporary SQLite files under `/tmp/week16-h006-evidence-20261003/` and independent processes for each command. All inputs are synthetic. Each command records separate stdout, stderr, and exit code.

### Week 16 acceptance tests

Command: `../../week15/human-in-the-loop-lab/.venv/bin/python -m pytest -q`

Exit code: 0

stdout:

```text
...........                                                              [100%]
11 passed in 7.42s
```

stderr:

```text
(empty)
```

### Week 13 regression tests

Command: `./.venv/bin/python -m pytest -q`

Exit code: 0

stdout:

```text
............................                                             [100%]
28 passed in 0.17s
```

stderr:

```text
(empty)
```

### Week 14 regression tests

Command: `./.venv/bin/python -m pytest -q`

Exit code: 0

stdout:

```text
..                                                                       [100%]
2 passed in 1.65s
```

stderr:

```text
(empty)
```

### Week 15 regression tests

Command: `./.venv/bin/python -m pytest -q`

Exit code: 0

stdout:

```text
...........                                                              [100%]
11 passed in 9.14s
```

stderr:

```text
(empty)
```

### Week 16 lock consistency

Command: `uv lock --check --offline --cache-dir /tmp/week16-uv-cache`

Exit code: 0

stdout:

```text
(empty)
```

stderr:

```text
Using CPython 3.12.13
Resolved 48 packages in 1ms
```

### S1 start

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/success.sqlite --thread-id s1 start --host router.lan`

Exit code: 0

stdout:

```text
PENDING APPROVAL
{
  "prompt": "Approve the mock proposed fix?",
  "proposal": {
    "action": "review_diagnosis",
    "failed_checks": [],
    "host": "router.lan"
  },
  "version": 1
}
```

stderr:

```text
(empty)
```

### S1 inspect

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/success.sqlite --thread-id s1 inspect`

Exit code: 0

stdout:

```text
{
  "thread_id": "s1",
  "run_status": "awaiting_approval",
  "cancel_requested": null,
  "cancel_observed_at": null,
  "checks": {
    "dns": {
      "status": "ok",
      "detail": "dns mock check passed for router.lan",
      "attempts": 1
    },
    "service": {
      "status": "ok",
      "detail": "service mock check passed for router.lan",
      "attempts": 1
    },
    "connectivity": {
      "status": "ok",
      "detail": "connectivity mock check passed for router.lan",
      "attempts": 1
    },
    "logs": {
      "status": "ok",
      "detail": "logs mock check passed for router.lan",
      "attempts": 1
    }
  },
  "values": {
    "host": "router.lan",
    "analysis": {
      "host": "router.lan",
      "checks": {
        "dns": {
          "status": "ok",
          "detail": "dns mock check passed for router.lan",
          "attempts": 1
        },
        "service": {
          "status": "ok",
          "detail": "service mock check passed for router.lan",
          "attempts": 1
        },
        "connectivity": {
          "status": "ok",
          "detail": "connectivity mock check passed for router.lan",
          "attempts": 1
        },
        "logs": {
          "status": "ok",
          "detail": "logs mock check passed for router.lan",
          "attempts": 1
        }
      },
      "failed_checks": []
    },
    "proposal": {
      "action": "review_diagnosis",
      "host": "router.lan",
      "failed_checks": []
    },
    "proposal_version": 1,
    "retry_nonce": 0
  },
  "next": [
    "await_approval"
  ],
  "pending_approval": {
    "prompt": "Approve the mock proposed fix?",
    "proposal": {
      "action": "review_diagnosis",
      "host": "router.lan",
      "failed_checks": []
    },
    "version": 1
  }
}
```

stderr:

```text
(empty)
```

### S1 approve

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/success.sqlite --thread-id s1 approve`

Exit code: 0

stdout:

```text
{
  "agent_observation": "agent-resumed:executed",
  "execution_status": "executed",
  "run_status": "completed",
  "thread_id": "s1"
}
```

stderr:

```text
(empty)
```

### S2 degraded start

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/degraded.sqlite --thread-id s2 start --fault exhaust:service`

Exit code: 0

stdout:

```text
PENDING APPROVAL
{
  "prompt": "Approve the mock proposed fix?",
  "proposal": {
    "action": "review_diagnosis",
    "failed_checks": [
      "service"
    ],
    "host": "lab.example"
  },
  "version": 1
}
```

stderr:

```text
(empty)
```

### S2 degraded inspect

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/degraded.sqlite --thread-id s2 inspect`

Exit code: 0

stdout:

```text
{
  "thread_id": "s2",
  "run_status": "awaiting_approval",
  "cancel_requested": null,
  "cancel_observed_at": null,
  "checks": {
    "dns": {
      "status": "ok",
      "detail": "dns mock check passed for lab.example",
      "attempts": 1
    },
    "service": {
      "status": "failed",
      "detail": "service exhausted transient mock failure",
      "attempts": 2
    },
    "connectivity": {
      "status": "ok",
      "detail": "connectivity mock check passed for lab.example",
      "attempts": 1
    },
    "logs": {
      "status": "ok",
      "detail": "logs mock check passed for lab.example",
      "attempts": 1
    }
  },
  "values": {
    "host": "lab.example",
    "analysis": {
      "host": "lab.example",
      "checks": {
        "dns": {
          "status": "ok",
          "detail": "dns mock check passed for lab.example",
          "attempts": 1
        },
        "service": {
          "status": "failed",
          "detail": "service exhausted transient mock failure",
          "attempts": 2
        },
        "connectivity": {
          "status": "ok",
          "detail": "connectivity mock check passed for lab.example",
          "attempts": 1
        },
        "logs": {
          "status": "ok",
          "detail": "logs mock check passed for lab.example",
          "attempts": 1
        }
      },
      "failed_checks": [
        "service"
      ]
    },
    "proposal": {
      "action": "review_diagnosis",
      "host": "lab.example",
      "failed_checks": [
        "service"
      ]
    },
    "proposal_version": 1,
    "retry_nonce": 0
  },
  "next": [
    "await_approval"
  ],
  "pending_approval": {
    "prompt": "Approve the mock proposed fix?",
    "proposal": {
      "action": "review_diagnosis",
      "host": "lab.example",
      "failed_checks": [
        "service"
      ]
    },
    "version": 1
  }
}
```

stderr:

```text
(empty)
```

### S3 cancel

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 cancel --reason demo-cancel`

Exit code: 0

stdout:

```text
{
  "cancel_requested": true,
  "reason": "demo-cancel",
  "thread_id": "s3"
}
```

stderr:

```text
(empty)
```

### S3 start after cancellation

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 start`

Exit code: 0

stdout:

```text
{
  "run_status": "cancelled_before_dispatch",
  "cancel_observed_at": "pre_dispatch",
  "dns_result": {
    "status": "cancelled",
    "detail": "not_run",
    "attempts": 0
  },
  "service_result": {
    "status": "cancelled",
    "detail": "not_run",
    "attempts": 0
  },
  "connectivity_result": {
    "status": "cancelled",
    "detail": "not_run",
    "attempts": 0
  },
  "logs_result": {
    "status": "cancelled",
    "detail": "not_run",
    "attempts": 0
  }
}
```

stderr:

```text
(empty)
```

### S3 inspect cancelled

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 inspect`

Exit code: 0

stdout:

```text
{
  "thread_id": "s3",
  "run_status": "cancelled_before_dispatch",
  "cancel_requested": {
    "requested_at": "2026-10-03 04:02:56",
    "reason": "demo-cancel"
  },
  "cancel_observed_at": "pre_dispatch",
  "checks": {
    "dns": {
      "status": "cancelled",
      "detail": "not_run",
      "attempts": 0
    },
    "service": {
      "status": "cancelled",
      "detail": "not_run",
      "attempts": 0
    },
    "connectivity": {
      "status": "cancelled",
      "detail": "not_run",
      "attempts": 0
    },
    "logs": {
      "status": "cancelled",
      "detail": "not_run",
      "attempts": 0
    }
  },
  "values": {
    "host": "lab.example",
    "retry_nonce": 0
  },
  "next": [],
  "pending_approval": null
}
```

stderr:

```text
(empty)
```

### S3 retry

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 retry`

Exit code: 0

stdout:

```text
PENDING APPROVAL
{
  "run_status": "awaiting_approval",
  "thread_id": "s3"
}
```

stderr:

```text
(empty)
```

### S3 inspect after retry

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 inspect`

Exit code: 0

stdout:

```text
{
  "thread_id": "s3",
  "run_status": "awaiting_approval",
  "cancel_requested": null,
  "cancel_observed_at": null,
  "checks": {
    "dns": {
      "status": "ok",
      "detail": "dns mock check passed for lab.example",
      "attempts": 1
    },
    "service": {
      "status": "ok",
      "detail": "service mock check passed for lab.example",
      "attempts": 1
    },
    "connectivity": {
      "status": "ok",
      "detail": "connectivity mock check passed for lab.example",
      "attempts": 1
    },
    "logs": {
      "status": "ok",
      "detail": "logs mock check passed for lab.example",
      "attempts": 1
    }
  },
  "values": {
    "host": "lab.example",
    "analysis": {
      "host": "lab.example",
      "checks": {
        "dns": {
          "status": "ok",
          "detail": "dns mock check passed for lab.example",
          "attempts": 1
        },
        "service": {
          "status": "ok",
          "detail": "service mock check passed for lab.example",
          "attempts": 1
        },
        "connectivity": {
          "status": "ok",
          "detail": "connectivity mock check passed for lab.example",
          "attempts": 1
        },
        "logs": {
          "status": "ok",
          "detail": "logs mock check passed for lab.example",
          "attempts": 1
        }
      },
      "failed_checks": []
    },
    "proposal": {
      "action": "review_diagnosis",
      "host": "lab.example",
      "failed_checks": []
    },
    "proposal_version": 1,
    "retry_nonce": 1
  },
  "next": [
    "await_approval"
  ],
  "pending_approval": {
    "prompt": "Approve the mock proposed fix?",
    "proposal": {
      "action": "review_diagnosis",
      "host": "lab.example",
      "failed_checks": []
    },
    "version": 1
  }
}
```

stderr:

```text
(empty)
```

### S3 approve

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/recovery.sqlite --thread-id s3 approve`

Exit code: 0

stdout:

```text
{
  "agent_observation": "agent-resumed:executed",
  "execution_status": "executed",
  "run_status": "completed",
  "thread_id": "s3"
}
```

stderr:

```text
(empty)
```

### S4 reject start

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/reject.sqlite --thread-id s4 start`

Exit code: 0

stdout:

```text
PENDING APPROVAL
{
  "prompt": "Approve the mock proposed fix?",
  "proposal": {
    "action": "review_diagnosis",
    "failed_checks": [],
    "host": "lab.example"
  },
  "version": 1
}
```

stderr:

```text
(empty)
```

### S4 reject

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false ../../week15/human-in-the-loop-lab/.venv/bin/python -m long_running_workflow_lab.cli --db /tmp/week16-h006-evidence-20261003/reject.sqlite --thread-id s4 reject`

Exit code: 0

stdout:

```text
{
  "agent_observation": "agent-resumed:rejected",
  "execution_status": "rejected",
  "run_status": "rejected",
  "thread_id": "s4"
}
```

stderr:

```text
(empty)
```

### S4 mock-fix log assertion

Command: `PYTHONPATH=src LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false python3 -c from pathlib import Path; p=Path('/tmp/week16-h006-evidence-20261003/reject-fix.jsonl'); print('exists='+str(p.exists())); print('calls='+str(len(p.read_text().splitlines()) if p.exists() else 0))`

Exit code: 0

stdout:

```text
exists=False
calls=0
```

stderr:

```text
(empty)
```
