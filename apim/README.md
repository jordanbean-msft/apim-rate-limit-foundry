# OpenAI gateway contracts

Terraform publishes explicit operations, not catch-all backend routes.
Only OpenAI Chat Completions and Responses are supported.

| Route | Contract |
|---|---|
| `POST /foundry/chat/completions` | Inline text/client functions; exactly one positive `max_tokens` or `max_completion_tokens`, `n=1` |
| `POST /foundry/responses` | Inline text/client functions; positive `max_output_tokens`; stateless foreground only |
| `GET /portal/{collection}` | `health`, `dashboard`, `models`, `budgets`, `organizations`, `prices`, `assignments`, `usage`, `audit`, `chargeback` |
| `GET /portal/budgets/status` | Authorized month-to-date user/team/department budget balances |
| `PUT`, `DELETE /portal/{collection}/{id}` | `budgets`, `organizations`, `prices`, `assignments`; Function independently enforces Admin |
| `POST /portal/counters/rebuild` | Admin-only durable-ledger counter rebuild |
| `POST /internal/usage-events` | Function workload only; native Event Hub logger callback, never inference |

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
Verified UTF-8/framing input bounds and explicit output caps still bound the text
request subset; those safety caps do not estimate or debit monetary usage.
Direct OpenAI accounts use their official `.openai.azure.com` (or sovereign)
inference origins, not Foundry project URLs.

## Monthly soft caps and actual accounting

1. Native RPM and optional verified TPM controls run first.
2. `limiter-budget-check` calls gateway-only `POST /api/budgets/check` with
   `{request_id, tenant_id, principal_id, subscription_id, model, api_protocol,
   streaming}`. The gateway generates the request ID.
3. The response's `request_id` must match. Errors fail closed; an exhausted
   configured user, team **or** department budget returns `429` and `Retry-After`.
4. The request is dispatched without predicting/debiting cost.
5. Nonstreaming outbound processing calls gateway-only `POST /api/usage/record`
   with `{request_id, provider_usage, status:"actual"}` using the complete provider
   `usage` object unchanged. Missing usage sends `status:"usage_unknown"` without
   invented tokens.
6. Python normalizes cached/uncached input and output and calculates the pinned
   version's actual micro-USD cost. APIM performs **no price math**. The immutable
   record and hierarchy counters remain authoritative.
7. Only a successful record response with `replayed:false` logs its returned
   `event` through native `log-to-eventhub`.

**These are soft monthly UTC-calendar USD caps.** Concurrent in-flight requests
can overshoot; the next request is denied. They are not strict financial ceilings.
The budget check snapshots the month, organization and price metadata required
for trusted recording, with no monetary hold. Completed request IDs cannot
dispatch another inference. Unknown usage is visible and unpriced, never zero.

Accounting callout/publish failures emit safe failure telemetry but preserve the
provider response. No Event Hub retries or Function-side Event Hubs SDK are used.
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
- Missing terminal usage, interruption or disconnect records `usage_unknown`.
- After durable recording the relay makes one best-effort call to the internal
  APIM callback with the returned event, only when not replayed.

`forward-request buffer-response="false"` is retained. Outbound policy body
inspection occurs **only** on the nonstream branch. Disabling the relay rejects
streaming requests rather than silently permitting unobserved streaming.

The callback does not require a subscription key. It instead validates the API
audience, tenant, **specific Function managed identity `oid` and `azp`**, and
`RateLimit.Gateway` app role; delegated scopes are forbidden. Browser/client
tokens, including Admin tokens, cannot forge usage. It has no backend forwarding.
Function callback settings are `APIM_USAGE_EVENT_URL` and `API_AUDIENCE`.

## Native Event Hub projection

`event_version:2`, `event_name:"usage_recorded"` flat events contain request/event
IDs, UTC month/time, opaque tenant/user references, team/department, business
unit/cost center, application subscription, model/protocol/stream flag, actual or
unknown status, normalized token categories, pinned price version and actual
micro-USD (null for unknown). No prompts, completions, human names, raw principal
IDs, bearer tokens or subscription keys are included.

The partition key is `tenant_ref:user_ref`. APIM is the only producer, using its
user-assigned managed identity and **hub-scoped Azure Event Hubs Data Sender**.
The logger is buffered and delivery is best effort, not a billing ledger or
exactly-once export. Only new durable records attempt publication.

Microsoft documents that `log-to-eventhub` is **not affected by Application
Insights sampling**, and messages over **200 KB are automatically truncated**.
The callback rejects events over 16 KiB; the normalized event is compact and must
remain below that bound. Do not log request/response payloads to work around it.
See the [policy reference](https://learn.microsoft.com/azure/api-management/log-to-eventhub-policy)
and [managed-identity logger guide](https://learn.microsoft.com/azure/api-management/api-management-howto-log-event-hubs).

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
stream delivery, callback rejection and forced Event Hub failure acceptance must
be performed in an approved test environment. No live provisioning is part of
this change. Review the destructive cutover and archive legacy configuration/
usage before applying Terraform, because removed service resources/APIs may be
destroyed rather than disabled.
