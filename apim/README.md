# OpenAI gateway contracts

Terraform publishes explicit operations, not catch-all backend routes.
Only OpenAI Chat Completions and Responses are supported.

| Route | Contract |
|---|---|
| `POST /foundry/chat/completions` | Inline text/client functions; exactly one positive `max_tokens` or `max_completion_tokens` within the model's `max_output_tokens`, `n=1` |
| `POST /foundry/responses` | Inline text/client functions; positive `max_output_tokens`; stateless foreground only |
| `GET /portal/{collection}` | `health`, `dashboard`, `models`, `budgets`, `organizations`, `prices`, `assignments`, `usage`, `chargeback` |
| `GET /portal/budgets/status` | Authorized month-to-date user/team/department budget balances |
| `PUT`, `DELETE /portal/{collection}/{id}` | `budgets`, `organizations`, `prices`, `assignments`; Function independently enforces Admin |

## Trust boundaries

Inference and portal APIs require **both** a native product subscription key and
an Entra bearer token. All-access/API-scoped subscriptions are rejected; the
requested API must belong to the provisioned product. Never put keys in URLs.
The portal's product key remains server-only in Key Vault.

APIM validates inference token signature, audience and tenant before reading
`tid`/`oid`. Inference requires a delegated person (`scp` present, `idtyp` not
`app`); application-only tokens and missing `oid` are rejected rather than
reinterpreted as people. The Function resolves an explicit enabled assignment
for that tenant/person. Caller user/team/department headers are never trusted.
`context.Subscription.Id` remains application attribution and the native RPM/TPM
key, **not** the monthly budget identity.

Backend selection preserves explicit APIM backend entities and managed-identity
authentication. `<protocol>:<alias>` resolves through the shared `MODEL_REGISTRY`;
the provider receives the registered deployment, not an arbitrary URL/model.
Only explicitly configured legacy aliases can be implicit defaults.
Each policy registry entry carries its `backend_id` (and `pool: true` for aliases
with additional endpoints), so the backend naming rule (`ai-model-<hash>` or
`ai-pool-<hash>`) lives only in Terraform. The policy parses the JSON body once
into `request-json` and the registry entry once into `model-entry`.
Nonstreaming pooled requests use `retry` (count 2, first fast retry, buffered
request body) on 429/5xx so another pool member is tried; member circuit breakers
come from Terraform. Budget check and usage recording stay outside the retry, so
a retried request is recorded once from the final response. Streaming requests
go to the Function relay and the primary endpoint, never the pool.
The admission contract checks only what affects cost or the input bound and
leaves the rest to the provider, which validates its own schema:

- allowed top-level fields; exactly one positive output-token cap within the
  model's `max_output_tokens` (Responses: required `max_output_tokens`); Chat
  `n=1`; boolean `stream`; no `store` (or Responses `background`); Responses
  `truncation` only `disabled`;
- 1-128 inline messages/input items with text-only content (media and opaque item
  references are rejected) and at most 128 function-type tools;
- input bound: the request body's UTF-8 byte size must not exceed the model's
  `max_input_tokens`, a conservative upper bound on tokens.

After the budget check, `limiter-strip-caller-headers` removes caller
credentials and provider override headers. The set-body step rewrites the model
to the provider deployment, forces `store=false`/`background=false` for Responses
and `stream_options.include_usage=true` for streaming Chat. These safety caps do
not estimate or debit monetary usage.
Direct OpenAI accounts use their official `.openai.azure.com` (or sovereign)
inference origins, not Foundry project URLs.

## Monthly soft caps and actual accounting

1. Native RPM and optional verified TPM controls run first.
2. `limiter-budget-check` calls gateway-only `POST /api/budgets/check` with
   `{request_id, tenant_id, principal_id, subscription_id, model, api_protocol,
   streaming}`. The gateway generates the request ID.
3. The response's `request_id` must match. Errors fail closed; Redis unavailable
   returns `503` without Table fallback. An exhausted configured user, team **or**
   department budget, including a zero limit, returns `429` and `Retry-After`.
4. The request is dispatched without predicting/debiting cost.
5. Nonstreaming outbound processing calls gateway-only `POST /api/usage/record`
   with `{request_id, provider_usage, status:"actual"}` using the complete provider
   `usage` object unchanged. Missing usage sends `status:"usage_unknown"` without
   invented tokens.
6. Python normalizes cached/uncached input and output and calculates the pinned
   version's actual micro-USD cost. APIM performs **no price math**. Redis
   atomically increments all six user/team/department wildcard/model counters
   together with a usage replay marker.
7. The nonstream call still waits briefly for Redis acceptance, but not for Table
   writes. APIM sets `X-RateLimit-Accounting: redis-accepted|unavailable` from the
   result. The Function itself publishes the finalized event to Event Hubs in the
   background after Redis accepts the first record (never for replays).

**These are approximate monthly UTC-calendar USD caps.** Concurrent in-flight
requests can overshoot; the next request is denied against recorded Redis spend.
Redis loss can reset that spend. These are not strict financial ceilings.
The budget check snapshots the month, organization and price metadata required
for trusted recording, with no monetary hold. Retained completed request IDs
cannot dispatch another inference; request context and replay protection last
24 hours, not forever. Unknown usage is unpriced, never zero.

Warm checks use Redis only. The shared configuration snapshot has a 60-second
default TTL; cold misses may read Table. Admin configuration CRUD remains
synchronous durable-first and invalidates the snapshot. Monthly counters last
about 62 days. No automatic ledger rebuild, global ledger lock or per-request
full ledger read is used.

Request/usage Table writes use a bounded in-process `asyncio` queue/task
(256 pending), with logged drops/failures and a best-effort two-second drain on
graceful close. APIM never awaits those writes; restart, failure or saturation can
lose them permanently. No durable queue, outbox, retry or exactly-once guarantee
exists. Events mean Redis accepted usage, not that Table persisted it; live spend
and persisted history/chargeback can disagree permanently.

Accounting callout/publish failures emit safe failure telemetry but preserve the
provider response. Event Hub publication has no retries. If an admitted
nonstreaming request has no captured provider response on error, APIM records
unknown usage and the Function charges the pinned upper bound.
The gateway strips client credentials/EasyAuth identity headers before upstream
dispatch and never sends prompts/completions to accounting routes.

## Streaming

APIM policies cannot reliably inspect terminal SSE usage without consuming the
response body. The narrow, dedicated Function relay is retained:

- APIM forces Chat `stream_options.include_usage=true`.
- APIM routes streaming requests to `POST /api/stream`, overwrites
  `X-Usage-Request-ID`, and authenticates with its Gateway managed identity.
- The relay looks up trusted request metadata, validates the registered
  deployment/body, and incrementally forwards SSE.
- Chat uses the final cumulative usage-only chunk before `[DONE]`; Responses
  uses usage on `response.completed`. Never sum token deltas.
- Missing terminal usage, interruption or disconnect attempts `usage_unknown`,
  never a fabricated zero-cost actual.
- At terminal usage the relay does Redis accounting in process, then schedules a
  best-effort background Event Hub publication of the returned event, only when
  not replayed. Neither accounting nor publication waits for Table persistence.

`forward-request buffer-response="false"` is retained. Outbound policy body
inspection occurs **only** on the nonstream branch. Disabling the relay rejects
streaming requests rather than silently permitting unobserved streaming.

The Functions publish to Event Hubs directly; APIM has no Event Hub logger,
internal usage-event API or Event Hub role. Function settings are
`EVENT_HUB_FQDN` and `EVENT_HUB_NAME` (both or neither; unset publishes nothing).

## Event Hub projection

`event_version:2`, `event_name:"usage_recorded"` flat events contain request/event
IDs, UTC month/time, opaque tenant/user references, team/department, business
unit/cost center, application subscription, model/protocol/stream flag, actual or
unknown status, normalized token categories, pinned price version and actual
micro-USD (null for unknown). No prompts, completions, human names, raw principal
IDs, bearer tokens or subscription keys are included.

The partition key is `tenant_ref:user_ref`. The Function publishes with the
`azure-eventhub` SDK (`EventHubProducerClient`) and its managed identity, which has
**Azure Event Hubs Data Sender** scoped to the hub. Delivery is a best-effort
background send with no retries, not a billing ledger or exactly-once export. Only
newly Redis-accepted usage attempts publication; this is not proof that either
Table history or downstream finance processing completed.

## Validation and cutover

```sh
uv run python -m pytest apim/tests -W error
uv run ruff check apim/tests
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra test
```

Offline tests render the complete XML and check trust/routing/accounting
contracts; they do not emulate APIM's C# policy runtime. Live policy compilation,
stream delivery and forced Event Hub failure acceptance must
be performed in an approved test environment. No live provisioning is part of
this change. Review the destructive cutover and archive legacy configuration/
usage before applying Terraform, because removed service resources/APIs may be
destroyed rather than disabled.
