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
Unsupported separately billed modalities/tools require an explicit future pricing
design; they must not be silently treated as free.
Azure may include `input_tokens_details.cache_write_tokens: 0`; this validated zero
does not add a charge. Nonzero or malformed cache-write counters remain unknown
usage because this sample has no separately billed cache-write price category.

## Interrupted streams

Disconnects, provider errors or missing terminal usage can prevent exact
accounting. Record `usage_unknown` in Redis with null token/cost fields and
schedule its best-effort Table mirror; report retained unknown records separately,
and never fabricate zero tokens or a guessed actual charge.
The gateway cannot recover exact provider billing by counting visible text:
reasoning, caching and partial provider work are not reconstructible that way.
When terminal usage is observed, attempt Redis accounting even if client delivery
fails afterward; this does not guarantee that Table history or export survives.

## Redis acceptance versus history

The admitted context pins month, membership and price in Redis for 24 hours.
Actual usage increments the six relevant monthly user/team/department
wildcard/model counters atomically with a 24-hour usage-idempotency marker.
Unknown usage remains unpriced, never a zero-cost actual. Redis loss can reset
spend or lose the context needed to record usage; there is no ledger rebuild.

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
