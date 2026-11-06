# APIM granular AI rate limiting

A reference sample for **Azure API Management + Microsoft Foundry + Python Azure Functions**.
It separates infrastructure protection (requests/tokens per minute) from consumption governance
(who may spend how much on which model or AI service).

APIM authenticates callers, routes to AI backends, and enforces the decision returned by the
Function. The Function owns pricing, granular rules, atomic reservations, and accounting.
A **React + Microsoft Fluent UI** portal provides configuration and usage visibility.

| LLM API | Gateway route | Accounting |
| --- | --- | --- |
| OpenAI Chat Completions | `POST /foundry/chat/completions` | Prompt/completion tokens and cached prompt subset |
| OpenAI Responses | `POST /foundry/responses` | Input/output tokens and cached input subset |
| Anthropic Messages | `POST /anthropic/v1/messages` | Uncached input, cache reads, 5-minute/1-hour cache writes, output |

These are native wire formats, not a conversion of Messages or Responses into Chat Completions.
Supported inline text and client-executed tool flows are bounded before dispatch; opaque media,
server-managed history and separately billed built-in tools are rejected. See
[gateway contracts](apim/README.md) for precise supported fields and deployment capability gates.

| Component | Responsibility |
| --- | --- |
| APIM | Identity, subscription governance, coarse native throttling, backend authentication, Function callouts |
| Python Functions | Cost/unit decisions, reservations, settlement, rules, price catalog, usage APIs |
| Redis-compatible store | Atomic shared hot counters; not the durable financial ledger |
| Azure Table Storage | Configuration and accounting/audit records |
| Fluent React portal | Admin configuration and scoped read-only consumption views |
| Application Insights / Log Analytics | Operational diagnostics and decision telemetry |

Supports **Azure Commercial and Azure Government** with explicit cloud configuration.
Foundry model availability, API versions, APIM tiers, networking, and Redis availability must be
validated for the target region/subscription. This is a sample, not a financial billing system
or a certification of GCCH/FedRAMP compliance.
Responses and Messages are explicitly opt-in. Responses requires additional Government capability
verification; Anthropic enablement in Government is currently rejected because sovereign Claude
availability is not established. Protocol support does not manufacture provider availability.

## What is different from native APIM limits?

APIM's native `llm-token-limit` counts prompt and completion tokens. It does not express a
versioned model price card with separate cache-read and cache-write prices. This sample can enforce cost or
usage rules by principal, model, service, and UTC period while retaining native APIM burst limits.

An admitted request reserves its conservative maximum cost. A trusted non-streaming response
settles actual usage, including cached input when reported by the provider. Streaming requests
remain conservatively charged unless trusted actual usage arrives; they are never refunded merely
because a timer expires. Cached input discounts do **not** bypass the provider's own TPM limits.
Anthropic cache writes can cost more than ordinary input: admission reserves the highest relevant
input price, and the Function normalizes provider-specific usage before settlement.

Document Intelligence and Language use their own units, not fictitious LLM token counts.
See [architecture and accounting](ARCHITECTURE.md) for boundaries and limitations.

## Development

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22.13+ LTS (or 24 LTS),
and Terraform 1.9+.
Optional local service integration uses Redis and Microsoft's Azurite Storage emulator.

```bash
uv sync --extra dev
npm --prefix web ci
uv run ruff check .
uv run pytest -W error
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
```

See [local development](docs/local-development.md), [configuration](docs/configuration-reference.md),
[deployment](docs/deployment.md), and [operations](docs/operations.md). Repository-scoped VS Code tasks cover setup, tests, builds,
formatting, type checking, infrastructure validation, and local processes.

## Deploy

Use **azd + Terraform** with a pre-created resource group and, for private deployments, existing
subnets and policy-managed private DNS. Configure the target cloud before authenticating.
No live Azure deployment is performed by running local tests.

```bash
azd provision
azd deploy
```

Follow the deployment guide first: cloud, state backend, identities, models, quota, network access,
and explicit Terraform inputs are prerequisites, not inferred defaults.
The complete input shape is in `infra/environment.example.json`; supported gateway routes and
payload restrictions are in [apim/README.md](apim/README.md).

**Redis lifecycle:** Commercial uses Azure Managed Redis. The Government compatibility path uses
Azure Cache for Redis, whose current retirement date is September 30, 2028. Do not select that
path for a production lifetime beyond its supported availability without an approved migration.

## Rate-limit custom traces

The Function exports structured `AppTraces` to workspace-based Application Insights.
`Message` and `Properties.event_name` identify the event; `event_version=1` versions
the allowlisted schema. `correlation_id` joins gateway requests and portal actions;
`reservation_id` joins admission, per-policy evaluation and settlement.

| Trace | Relevant custom properties |
|---|---|
| `rate_decision` | Service/model/protocol, allowed/reason, matched/denied policies, retry/reset, replayed, conservative `reserved_cost_micro_usd`, admitted `cost_micro_usd` (zero on denial) |
| `reservation_policy_debit` | Policy/unit, requested `amount`, limit/remaining, `applied_amount` (zero on denial), `policy_outcome`: allowed, denied (binding policy), or blocked (another policy rejected the request) |
| `settlement_recorded` | Actual/conservative status, estimated, usage/cache counters, price version, final cost, original reserved cost and returned liability |
| `settlement_policy_debit` | Per-policy final amount, original `reserved_amount`, `applied_amount`, `refunded_amount` |
| `dependency_completed`, `operation_failed` | Redis/Table operation, latency, success/error type without exception text |

Deduplicate admissions by reservation and policy evaluations by reservation/policy.
Deduplicate settlements by reservation before summing usage or cost: idempotent retries
can emit another observation without spending again. `applied_amount` describes the
reservation's debit, **not** an incremental write on replay. Refunds release conservative
liability; they are not invoice credits or necessarily cache savings. Remaining values
are per-principal policy observations, not a global live Redis balance.
Telemetry is asynchronous operational evidence; durable usage records remain the
accounting source of truth. Prompts, document bodies, auth headers, raw identities
and Redis keys are excluded from application custom properties.

## Sources

- [APIM advanced request throttling](https://learn.microsoft.com/azure/api-management/api-management-sample-flexible-throttling)
- [APIM LLM token limit policy](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy)
- [Original custom rate limiter sample](https://github.com/ThePreston/Custom-Rate-Limiter-API)
- [Azure Government comparison](https://learn.microsoft.com/azure/azure-government/compare-azure-government-global-azure)
- [Foundry cloud/region support](https://learn.microsoft.com/azure/foundry/reference/region-support)
- [Azure OpenAI Responses API](https://learn.microsoft.com/azure/foundry/openai/how-to/responses)
- [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
- [Anthropic prompt-cache semantics](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. See [LICENSE](LICENSE).
