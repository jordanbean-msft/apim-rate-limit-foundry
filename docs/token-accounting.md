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
accounting. Persist `usage_unknown` with null token/cost fields, report it
separately, and never fabricate zero tokens or a guessed actual charge.
The gateway cannot recover exact provider billing by counting visible text:
reasoning, caching and partial provider work are not reconstructible that way.
Completed usage remains accountable even if client delivery fails afterward.

## Native APIM export

`log-to-eventhub` is an outbound integration policy, not an SSE token accumulator.
Do not read/buffer an SSE response body merely to produce an event. The retained
OpenAI relay records terminal usage and calls a protected internal APIM operation
which invokes the native Event Hub logger. APIM is the sole Event Hub producer.

## Research references

- [OpenAI Chat stream options](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [APIM token metrics](https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy)
- [APIM Event Hub policy](https://learn.microsoft.com/azure/api-management/log-to-eventhub-policy)

APIM token metrics themselves warn that interrupted streams can produce
inaccurate counts. Native operational token metrics do not replace the durable
per-request ledger, and platform-specific gateway examples do not prove a feature
exists in an arbitrary APIM SKU or Government deployment.
