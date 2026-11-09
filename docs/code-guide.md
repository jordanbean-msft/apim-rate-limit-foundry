# Code guide

The public inference surface is Azure OpenAI Chat Completions and Responses behind
APIM. Python is responsible for organization membership, monthly dollar budgets,
versioned pricing, actual usage and authorized reports.

| Component | Responsibility |
| --- | --- |
| `api.py`, `auth.py` | FastAPI contracts and independent Gateway/Admin/Reader authorization |
| `models/` | Typed organization, assignment, budget, price and usage contracts |
| `engine.py`, `accounting.py` | Read-only budget decisions and idempotent actual-cost accounting |
| `stores/` | Durable records and monthly counter projection |
| `streaming/` | Incremental OpenAI SSE relay and terminal-usage observation |
| `reports/` | Scoped spend/chargeback and Admin-only shared Azure dashboard queries |
| `runtime.py`, `config.py` | Dependency injection, lifecycle and centralized settings |
| `telemetry.py` | Allowlisted structured events without prompts or credentials |

`function_app.py` and `stream/function_app.py` are separate Function entry points
because the streaming host uses HTTP streaming extensions. Neither performs agent
orchestration: the relay preserves the native OpenAI protocol.

Do not add independent price arithmetic to APIM, KQL or the browser. The immutable
usage record and its pinned price version are authoritative. Event Hub messages
are a best-effort projection of that record, not another accounting service.

See [architecture](../ARCHITECTURE.md), [API contracts](configuration-reference.md),
and [local validation](local-development.md).
