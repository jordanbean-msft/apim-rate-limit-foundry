# Code guide

The public inference surface is Azure OpenAI Chat Completions and Responses behind
APIM. Python is responsible for organization membership, monthly dollar budgets,
versioned pricing, actual usage and authorized reports.

| Component | Responsibility |
| --- | --- |
| `api.py`, `auth.py` | FastAPI contracts and independent Gateway/Admin/Reader authorization |
| `models/` | Typed organization, assignment, budget, price and usage contracts |
| `engine.py`, `accounting.py` | Redis-recorded-spend decisions without reservations and replay-protected actual-cost accounting |
| `stores/` | Durable configuration/history and Redis operational configuration/context/replay/spend |
| `background_writer.py` | Bounded process-local best-effort request/usage Table writer |
| `streaming/` | Incremental OpenAI SSE relay, in-process terminal Redis accounting and background APIM callback |
| `reports/` | Scoped spend/chargeback and Admin-only shared Azure dashboard queries |
| `runtime.py`, `config.py` | Dependency injection, lifecycle and centralized settings |
| `telemetry.py` | Allowlisted structured events without prompts or credentials |

`function_app.py` and `stream/function_app.py` are separate Function entry points
because the streaming host uses HTTP streaming extensions. Neither performs agent
orchestration: the relay preserves the native OpenAI protocol.

Do not add independent price arithmetic to APIM, KQL or the browser. The immutable
usage context pins its price version. Redis acceptance drives live approximate
budgets; eventual Table history drives reports. Warm admission never reads Table;
cold configuration misses may. Admin CRUD is durable-first and invalidates shared
configuration. Actual usage increments all six hierarchy wildcard/model counters
atomically with its replay marker. There is no global ledger lock or rebuild.
Event Hub messages mean Redis accepted usage, not that Table persisted it. The
background writer's bounded queue can drop/lose writes, so neither history nor
events promise financial completeness. See [operations](operations.md) for TTLs
and failure behavior.

See [architecture](../ARCHITECTURE.md), [API contracts](configuration-reference.md),
and [local validation](local-development.md).
