# Actual tokens and streaming

**Use the provider's final totals once. Do not sum streaming chunks.**

| API | Trusted usage location | Handling |
| --- | --- | --- |
| Chat, JSON | Response `usage` | Normalize `prompt_tokens`, `completion_tokens`, cached-input detail |
| Chat, SSE | Usage-only chunk before `[DONE]`, requested with `stream_options.include_usage=true` | Ignore null intermediate usage; retain final object once |
| Responses, JSON | Response `usage` | Normalize `input_tokens`, `output_tokens`, cached-input detail |
| Responses, SSE | Terminal `response.completed` usage (or validated incomplete terminal response) | Read the cumulative object once, not text deltas |

The relay observes bounded SSE events while forwarding bytes incrementally.
HTTP chunk boundaries can split JSON, UTF-8 characters and SSE delimiters; they
are not token or event boundaries. Clients may see usage-only chunks with an
empty `choices` array and must not blindly access `choices[0]`.

`STREAM_MAX_EVENT_BYTES` (64 KB by default) bounds the bytes the observer
*retains*, not the size of the stream. Responses `response.completed` embeds the
whole generated output, so it routinely exceeds that bound. A larger Responses
`data:` line is scanned as it streams past: only its `type`, `response.status`
and `response.usage` (itself capped at the same bound) are kept and the `output`
is discarded, so large generations are priced from their real usage. An oversized
Chat event, an oversized usage object, or malformed JSON still makes the stream's
usage unknown (see below). Client bytes are never modified.

## Price calculation

OpenAI cached input is already included in total input. For example, 10,000 input
tokens with 9,000 cached tokens means 1,000 uncached tokens, not 19,000 input.

```text
uncached input = input_tokens - cached_input_tokens
cost = uncached input * input price
     + cached input * cached-input price
     + output tokens * output price
```

Rates are USD per million tokens. Decimal arithmetic converts the total to integer
micro-USD, with conservative rounding at the final cost. Provider output totals
already contain reasoning token subsets: do not add them a second time.
Unsupported separately billed modalities/tools (for example nonzero audio tokens)
require an explicit future pricing design; they must not be silently treated as
free, so they make usage unknown. A `null` audio counter, in either input or
output details, counts as absent.

### Cache-write tokens

Providers may report `input_tokens_details.cache_write_tokens`. Like cached
tokens they are a subset of input, so cached + cache-write may not exceed input.
Normalized usage is the typed `UsageCounts` model (`input_tokens`,
`cached_input_tokens`, `cache_write_tokens`, `output_tokens`) and is recorded on
the usage event.

```text
uncached input = input_tokens - cached_input_tokens - cache_write_tokens
cost = uncached input * input price
     + cached input * cached-input price
     + cache-write tokens * (cache_write_per_million, else input price)
     + output tokens * output price
```

`cache_write_per_million` is an optional field of a price card. When absent,
cache-write tokens are charged at the **uncached input rate**, the conservative
choice that also reproduces the old arithmetic when the counter is zero.
Malformed (negative, boolean, non-integer, `null`) cache-write counters make the
usage unknown.

### Usage above the model bounds

Admission pins the model's `max_input_tokens` and `max_output_tokens` (the
registered deployment's, or the host-wide `MAX_INPUT_TOKENS`/`MAX_OUTPUT_TOKENS`
without a registry). Valid provider usage above those bounds is **priced with its
real counts**, never discarded: the event carries `out_of_bounds: true` and a
`usage_out_of_bounds` warning is logged so operators can investigate a
misconfigured ceiling.

## Unknown usage and interrupted streams

Disconnects, provider errors, failed provider opens, missing or malformed
usage can prevent exact accounting. The request is recorded with
`status: usage_unknown` and null token counts, never fabricated zero tokens, and
is charged a **conservative, documented fallback** so budgets still decrement:

```text
estimated charge = pinned max_input_tokens  * input price (uncached rate)
                 + pinned max_output_tokens * output price
```

Everything comes from the immutable admission context (its pinned price and
model bounds), so editing prices or the registry afterwards cannot change it.
The ceiling is deliberately pessimistic: it assumes the largest admitted input
and output. Actual usage is not reconstructible by counting visible text:
reasoning, caching and partial provider work are not, so no better guess exists.
The request body is not inspected for a smaller `max_tokens`; operators who want
a tighter bound should lower the registered model's token ceilings.

Such records are marked `cost_basis: estimated_upper_bound` (provider-priced
events are `provider_usage`) and:

- increment the same six monthly counters as an actual charge, atomically with
  the replay marker;
- are published to Event Hub with `status: usage_unknown`, null tokens, a non-null
  `cost_micro_usd` and the basis, so consumers must not treat non-null cost as
  proof of provider-reported usage;
- are grouped separately in chargeback by status and `cost_basis`: tokens stay
  null, `unknown_requests` counts them and `cost_micro_usd` sums the estimates
  (null only for history written before estimates existed);
- add to the `limiter.usage.cost` metric under their own `cost_basis` attribute.

The stream relay uses one shielded finalization path for completion, provider
errors and client disconnects: observed terminal usage is priced as actual,
otherwise the unknown fallback is charged. When terminal usage was observed,
accounting is attempted even if client delivery fails afterward; this does not
guarantee that Table history or export survives. Valid usage seen before a
disconnect is therefore never replaced by the estimate.

## Redis acceptance versus history

The admitted context pins month, membership and price in Redis for 24 hours.
Actual usage increments the six relevant monthly user/team/department
wildcard/model counters atomically with a 24-hour usage-idempotency marker.
Unknown usage is charged the upper-bound fallback above, never treated as a
zero-cost actual. Redis loss can reset spend or lose the context needed to record
usage; there is no ledger rebuild.

Nonstreaming APIM accounting waits briefly for Redis acceptance and receives the
event on `200`, not for Table persistence. Request/usage Table writes use a
256-pending process-local async writer, with logged drops/failures and a
best-effort two-second graceful-close drain. Lost writes are accepted; no durable
queue, outbox, retry or exactly-once guarantee exists. Live budgets and persisted
history/chargeback can differ permanently.

## Native APIM export

`log-to-eventhub` is an outbound integration policy, not an SSE token accumulator.
Do not read/buffer an SSE response body merely to produce an event. The retained
OpenAI relay forwards chunks incrementally, does terminal Redis accounting in
process, and schedules a best-effort background callback to a protected internal
APIM operation which invokes the native Event Hub logger. APIM is the sole Event
Hub producer. An event means Redis accepted the usage, not that Table persisted
it, and callback scheduling does not guarantee publication.

## Research references

- [OpenAI Chat stream options](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [APIM token metrics](https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy)
- [APIM Event Hub policy](https://learn.microsoft.com/azure/api-management/log-to-eventhub-policy)

APIM token metrics themselves warn that interrupted streams can produce
inaccurate counts. Native operational token metrics do not make incomplete
per-request history financially complete, and platform-specific gateway examples do not prove a feature
exists in an arbitrary APIM SKU or Government deployment.
