# Gateway surface and supported bounds

Terraform creates explicit APIM operations; there are no catch-all backend routes.
Only enabled AI services are published. The portal API is always published.

| Route | Request / accounting model |
|---|---|
| `POST /foundry/chat/completions` | Bounded inline Chat text/client functions; exactly one `max_tokens` or `max_completion_tokens`, `n=1` |
| `POST /foundry/responses` | Bounded inline Responses text/client functions; required `max_output_tokens`; stateless foreground only |
| `POST /anthropic/v1/messages` | Bounded Messages text/system/client tools/cache controls; required `max_tokens`; full verified context input reserved |
| `POST /document-intelligence/analyze?pages=1-N` | Inline JSON `base64Source` PDF, `N` 1–20; configured `prebuilt-read` model; remote URLs, images and unspecified pages rejected |
| `GET /document-intelligence/analyzeResults/{operationId}` | Owned analysis polling only; no new reserve/debit; forwarded `Operation-Location` never exposes the raw AI endpoint |
| `POST /language/sentiment` | JSON `documents`: 1–10 `{id,text,language?}` records, each 1–5120 characters; model `sentiment` |
| `GET /portal/{collection}` | `health`, `policies`, `prices`, `assignments`, `usage`, `audit`, `reconciliation` |
| `GET /portal/usage/summary?period=hour\|day` | Derived scoped usage/cost rollups; default period `day` |
| `PUT`, `DELETE /portal/{collection}/{id}` | `policies`, `prices`, `assignments`; Function independently enforces Admin |
| `POST /portal/reconciliation/recover` | Explicit Admin cache-recovery operation |

AI clients either supply an Entra bearer token for `GATEWAY_CLIENT_AUDIENCE` (validated
by APIM against the configured tenant before claims are read), or a valid APIM
subscription whose **ID** has an explicit `subscription_tenant_mapping`. The default
mapping is empty: subscriptions/products must be independently configured before
enabling this mode. Keys are never principal IDs or telemetry dimensions.

The gateway generates request IDs. It never accepts caller prices, limits, usage
estimates or assumed cached-input discounts. LLM requests reject unknown/unsupported
properties rather than silently dropping their semantics. The gateway preserves supported
fields, pins backend model/API version, limits bodies to 1 MiB, enforces requested output/page
caps, and reserves before dispatch. A supplied model must match the configured deployment;
omitting it uses that deployment. Output caps are positive integers up to the operator's
`gateway.max_output_tokens` (4096 in the deployment example).
Language records use **sum of per-document ceiling(chars/1000)**, not ceiling of a batch.
Each AI route pins the operator's `*_PRICE_VERSION`; caller-supplied catalog versions
are ignored. Publish and validate a catalog version before deploying a route pin to it.

Policy fragments contain only statements, not sections or `<base>`. Native
`rate-limit-by-key` burst protection executes before the external reservation.
Optional `llm-token-limit` is disabled unless Commercial capability has been explicitly
verified; it executes before reservation with a tenant-qualified principal key, so native
denials cannot debit the budget ledger. It applies to Chat only, never Responses or Messages.
Unknown prices are rejected by the limiter.

## LLM wire formats

All three routes account as `service=foundry`, with explicit reserve `api_protocol`
values `openai-chat`, `openai-responses`, and `anthropic-messages`. The original
reservation determines settlement protocol; clients cannot override it later.

| Protocol | Operator-pinned upstream route | Version/auth contract |
|---|---|---|
| Chat | `/openai/deployments/{deployment}/chat/completions` | Existing configured dated `api-version`; explicit resource audience |
| Responses | `/openai/v1/responses` | Its own `RESPONSES_API_VERSION=v1\|preview`; explicit audience, commonly `https://ai.azure.com` |
| Messages | `/anthropic/v1/messages` | `ANTHROPIC_VERSION` becomes `anthropic-version`; no `api-version`; explicit audience, commonly `https://ai.azure.com` |

Managed identity supplies upstream Authorization. Caller query parameters are not copied;
caller API keys, `anthropic-beta`, organization and browser-access headers are removed.
Messages uses a separately referenced Foundry AI Services account, not an OpenAI-kind
resource created for Claude. Responses may reference the same account as Chat.

**Chat:** 1–128 system/developer/user/assistant/tool messages, string or inline text
blocks, optional names, assistant function calls and inline tool results.
Up to 128 inline function definitions/calls per array; function parameters are inline JSON.
Supports `tool_choice`, `parallel_tool_calls`, numeric `temperature`, `top_p`,
presence/frequency penalties, integer `seed`, bounded textual `stop`, and enumerated
`reasoning_effort`. Exactly one output cap is required; `n`, when supplied, must be 1.
`store=true`, legacy function formats, structured-output extensions, media and opaque
references are unsupported.

**Responses:** `input` is text or 1–128 inline messages/function-call/function-call-output
items; message content is text or up to 128 `input_text`/assistant `output_text` blocks.
Only empty output annotations are accepted. Optional text `instructions`, inline function
definitions, `tool_choice`, `parallel_tool_calls`, temperature/top-p and enumerated reasoning
effort are preserved. Sends `store=false` and `background=false`; supplied true values reject.
History IDs, `previous_response_id`, item references, encrypted reasoning, automatic
truncation, media/files and provider-built-in tools are rejected.

**Messages:** 1–128 user/assistant messages; text system prompt or up to 128 text system
blocks; string content or up to 128 text/tool-use/tool-result blocks.
Assistant `tool_use` has inline JSON input; user `tool_result` has inline text/string
blocks. Up to 128 inline custom tools, supported `tool_choice`, temperature/top-p/top-k,
up to 16 stop sequences and textual `metadata.user_id` are preserved.
`cache_control` accepts only `{type:"ephemeral", ttl:"5m"|"1h"}` (TTL optional).
Media, citations, thinking, provider-executed tools and other fields reject.

All protocols reject caller pricing-tier, batch, speed and inference-geography overrides.
Only standard-tier text inference is covered by the pinned price baseline. A provider
validation error is not proof of no work and never automatically refunds a reservation.

Chat/Responses reserve UTF-8 bytes of the **entire** JSON (including schemas/tool arguments)
plus framing overhead, not just prompt strings. Operators must verify the selected deployment's
byte tokenizer/framing bound before setting the explicit verification flags. Requests whose
conservative bound exceeds Function `MAX_INPUT_TOKENS` reject before reserve. This is not a
universal tokenizer claim. Messages instead reserves the entire operator-verified
`ANTHROPIC_CONTEXT_INPUT_TOKENS`, even for a short request; see the mandatory hard-cap
verification in [the infrastructure notes](../infra/README.md#protocol-enablement-and-hard-input-cap-verification).
Anthropic admission requires explicit uncached/read/write-5m/write-1h prices and uses the
most expensive possible input dimension, never an assumed cache discount.

Limiter backend URLs are exactly `/api/decisions/reserve`, `/settle`, `/release` under
`/api/decisions` (release is intentionally **not** invoked by these policies).
Trusted operation binding/checking calls are `/api/operations/bind` and `/check` under
`/api/operations`, using the gateway application role. Document owner metadata includes
tenant, canonical principal, model and reservation. Bind failures are fail-closed and
do not leak the backend `Operation-Location`.

Nonstreaming successful JSON response usage is read with `preserveContent: true`.
Only the small backend `usage` object (at most 8192 UTF-8 bytes), never prompt/response
content, is forwarded as `provider_usage`; DI/Language continue sending normalized `usage`.
Known integer counters/details and bounded tier/geography metadata are forwarded; unknown
dimensions or malformed values skip settlement rather than being silently discarded.
Function normalizes Chat/Responses counts or Anthropic uncached + cache-read + both cache-write
TTLs from the reserved protocol. Incomplete counters, unsupported billable dimensions and
ambiguous TTL totals remain conservative; they are never replaced with zero.
An absent OpenAI cached-token count is never fabricated as zero:
the limiter retains estimated cost and the gateway preserves its `data.estimated` flag,
even when settlement returns HTTP 200. Streaming responses are forwarded with
`buffer-response=false` and **never read by outbound policies** (including an unexpected
event-stream response to a nonstream request); their worst-case
reservation remains until trusted telemetry reconciliation or conservative timer
finalization. Transport errors and ambiguous backend errors never auto-refund.
Language HTTP 200 settles trusted `showStats=true` transaction counts; if those statistics
are absent the submitted per-document reservation remains conservative (including Unicode
UTF-16 overestimation rather than undercharging). Document polling settles only successful result page
counts. All other outcomes retain their conservative charge.

Headers: `RateLimit-Remaining`, `RateLimit-Reset`, `X-RateLimit-Reservation`,
`X-RateLimit-Estimated`; denials additionally return `Retry-After` and the decision JSON.
Remaining is a last-decision snapshot, not an independently queried live balance.
No prompt text, document bytes, subscription secrets, or auth tokens enter limiter calls.

Offline checks render every service policy and verify XML and key contract invariants:
`uv run python -W error -m unittest discover -s apim/tests -v`.
APIM's live policy compiler and sovereign service API versions still require a configured
deployment smoke test; the structural tests do not pretend to emulate APIM execution.
