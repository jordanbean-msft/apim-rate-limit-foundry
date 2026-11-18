---
title: Actual tokens and streaming
description: Provider usage normalization, cache pricing, SSE observation and unknown-usage estimates.
---

## Provider totals

**Use the provider's final totals once. Do not sum streaming chunks.**

| API             | Trusted usage location                                                               | Handling                                                            |
| --------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| Chat, JSON      | Response `usage`                                                                     | Normalize `prompt_tokens`, `completion_tokens`, cached-input detail |
| Chat, SSE       | Usage-only chunk before `[DONE]`, requested with `stream_options.include_usage=true` | Ignore null intermediate usage; retain final object once            |
| Responses, JSON | Response `usage`                                                                     | Normalize `input_tokens`, `output_tokens`, cached-input detail      |
| Responses, SSE  | Terminal `response.completed` usage (or validated incomplete terminal response)      | Read the cumulative object once, not text deltas                    |

The relay observes bounded SSE events while forwarding bytes incrementally.
HTTP chunk boundaries can split JSON, UTF-8 characters and SSE delimiters; they
are not token or event boundaries. Clients may see usage-only chunks with an
empty `choices` array and must not blindly access `choices[0]`.

`STREAM_MAX_EVENT_BYTES` (64 KB by default) bounds the bytes the observer
*retains*, not the size of the stream. Responses `response.completed` embeds the
whole generated output, so it routinely exceeds that bound. For Responses only, a
single oversized `data:` line is kept in full (up to a hard 1 MiB cap) when its
JSON starts with `"type":"response.completed"` or `"response.incomplete"`, the key
order providers use; other oversized Responses lines, such as
`response.output_text.done` carrying the full text, are discarded. Large
generations are therefore priced from their real usage. An oversized Chat event,
a terminal event over 1 MiB, malformed framing, or a usage object over 8192 bytes
makes the stream's usage unknown (see below). Client bytes are never modified.

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

Disconnects, gateway-side failures after admission, missing or malformed
usage can prevent exact accounting. A provider HTTP error response (4xx/5xx,
including provider throttling) generated no tokens, so the gateway does not
record or charge it. The same holds for a stream whose first events are a
`rate_limit_exceeded` error before any output; the relay records nothing. Any other
stream failure, or a throttle after output began, is still unknown usage. The request is recorded with
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

## Recording and export

The [architecture](../ARCHITECTURE.md#request-and-accounting-flow) describes
Redis acceptance and the shared best-effort history/export queue. The provider
does not call accounting directly: APIM records nonstreaming usage, and the
relay records streaming usage in process. Event Hub messages carry the finalized
event, including `cost_basis`; they do not prove Table persistence.

See [operations](operations.md) for retention and failure handling,
[observability](observability.md) for event delivery and telemetry, and
[chargeback](chargeback.md) for grouping actual and estimated charges.

## Research references

- [OpenAI Chat stream options](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [APIM token metrics](https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy)

APIM token metrics themselves warn that interrupted streams can produce
inaccurate counts. Native operational token metrics do not make incomplete
per-request history financially complete, and platform-specific gateway examples do not prove a feature
exists in an arbitrary APIM SKU or Government deployment.
