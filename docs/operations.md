# Operations and acceptance scenarios

## What to monitor

Track decision latency separately from AI backend latency. A fast Redis lookup does not remove
Function HTTP, identity, network, durable-write, or cold-start latency. Load-test the complete
`APIM -> Function -> stores -> APIM` admission path with realistic principal/model distributions.
Use warm-capacity hosting for predictable latency where available in the target cloud.

Monitor:

- Allowed/denied requests and denial rule/service/model, without logging request contents.
- Outstanding estimated reservations, age, amount, and actual-versus-estimated reconciliation.
- Redis availability/memory/evictions, ambiguous writes, and counter recovery state.
- Durable event/configuration failures, Function exceptions, backend `429`/`5xx`, and APIM
  callout timeouts. Distinguish provider throttling from custom budget denial.
- Platform diagnostic ingestion failures, data retention, and authorization failures.

The portal's scoped usage view and durable records are accounting aids. Sampled Application
Insights logs and emitted native APIM metrics must not be used to reconstruct an exact invoice.

## Operator acceptance checklist

Perform in a disposable, configured environment before admitting real traffic. Prices in
`examples/` are illustrative, not Azure list prices or contractual charges.

| Scenario | Expected result |
| --- | --- |
| Ordinary model request under the configured limits | One reservation, one backend dispatch, actual non-streaming settlement |
| Concurrent requests near a hard configured allowance | No partial multi-rule debit; successful reservations consume the shared remaining allowance |
| Repeated reservation/settlement delivery | No duplicate accounting or refund |
| Different tenants using the same subject ID | Distinct budget/usage scopes |
| Spoofed `Rate-Key`, principal header, or cached-token count | Ignored or rejected; no caller-selected limit bypass |
| Real reported cached prompt tokens | Discount applied only to the cached subset, using the reservation's price version |
| OpenAI Responses usage | Input/output and input-details cached subset normalize without Chat field assumptions |
| Anthropic cache reads and mixed-TTL writes | Raw uncached input is not reduced twice; cache writes use their own 5-minute/1-hour prices |
| Anthropic missing/mismatched cache metadata | Conservative accounting, never fabricated zero-cost reads/writes |
| Unsupported opaque content, background jobs or provider built-in tools | Explicit rejection before reservation/dispatch |
| All three streaming protocols | No outbound SSE parsing or automatic refund; conservative debit remains visible |
| Missing usage or interrupted stream | Conservative consumption remains visible; not silently converted to zero |
| Price-card change during an in-flight call | Existing reservation uses pinned prices; new reservations use the configured version |
| UTC period rollover with an in-flight call | Settlement adjusts the original period, not the next one |
| Redis restart/counter loss | Admission fails closed until an authorized recovery proves/rebuilds durable state |
| Durable storage failure after reservation | No unrecorded backend dispatch or automatic refund |
| Function timeout or malformed decision | Operational failure response; no AI request dispatched without admission |
| Language batch of short documents | Per-document record rounding, not one record for the entire batch |
| Document analysis submitted, then polled | Gateway operation URL and submitting-principal binding; no second analysis debit on poll |
| Consumer portal role | Own authorized usage only; no config mutations or another principal's audit history |
| Government environment | Authority/audience/endpoints remain Government-only; no Commercial fallback |

## Recovery

Stop or fail-close admission before rebuilding counters. Preserve durable evidence of every
potentially dispatched reservation, and treat unknown outcomes conservatively.
Do not flush shared Redis state, delete accounting events, or reset budgets to get requests moving.
Use only the backend's protected recovery mechanism and verify its readiness gate before reopening
traffic. A corrupted or incomplete durable history requires operator investigation rather than an
automatic reset.

For a deployed gateway, call the APIM portal API with an administrator **access token**:

```bash
curl --fail-with-body -X POST "$APIM_GATEWAY_URL/portal/reconciliation/recover" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

The token must target the configured API audience and carry `RateLimit.Admin`. Do not send it to
an unverified URL or substitute a Function key. The local-only equivalent is documented separately.

When correcting a record, preserve the original event and the reason/identity of the adjustment.
Rotating a price card or changing a budget is not the same as refunding previous usage.

## Production decisions not supplied by a sample

Document your expected throughput, decision latency objective, outage behavior, recovery point/time
objectives, maximum request size/units, geographic topology, retention, privacy requirements,
pricing governance, and ownership of reconciliation.

Choose a supported Redis lifecycle for the target cloud. The Government compatibility resource is
time-bounded by the legacy Cache for Redis retirement. Also validate that all Private Link
endpoints, deployment tools/runners, and diagnostic egress paths are allowed by your network policy.
The sample is not a promise of exact cloud invoice matching or zero-loss recovery across arbitrary
distributed failures.
