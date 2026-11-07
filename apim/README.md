# Gateway surface and supported bounds

Terraform creates explicit APIM operations; there are no catch-all backend routes.
Only enabled AI services are published. The portal API is always published.
This guide owns the wire/policy contract. For deployment inputs use
[infrastructure](../infra/README.md); for token audiences and role trust use
[Azure topology](../docs/azure-topology.md#identity-and-token-boundaries).

The managed model backend is a native Foundry `AIServices` account. Its
OpenAI-compatible Chat/Responses URLs and OpenAI User roles remain valid after
the [in-place account upgrade](../docs/deployment.md#upgrade-an-existing-openai-account);
do not replace inference origins with Foundry project URLs. Model lookup,
versioned pricing and Messages' separately verified identity/endpoint are unchanged.

| Route | Request / accounting model |
|---|---|
| `POST /foundry/chat/completions` | Bounded inline Chat text/client functions; exactly one `max_tokens` or `max_completion_tokens`, `n=1` |
| `POST /foundry/responses` | Bounded inline Responses text/client functions; required `max_output_tokens`; stateless foreground only |
| `POST /anthropic/v1/messages` | Bounded Messages text/system/client tools/cache controls; required `max_tokens`; full verified context input reserved |
| `POST /document-intelligence/analyze?pages=1-N` | Inline JSON `base64Source` PDF, `N` 1–20; configured `prebuilt-read` model; remote URLs, images and unspecified pages rejected |
| `GET /document-intelligence/analyzeResults/{operationId}` | Owned analysis polling only; no new reserve/debit; forwarded `Operation-Location` never exposes the raw AI endpoint |
| `POST /language/sentiment` | JSON `documents`: 1–10 `{id,text,language?}` records, each 1–5120 characters; model `sentiment` |
| `GET /portal/{collection}` | `health`, `models`, `subscriptions`, `policies`, `prices`, `assignments`, `usage`, `audit`, `reconciliation` |
| `GET /portal/usage/summary?period=hour\|day` | Derived scoped usage/cost rollups; default period `day` |
| `GET /portal/usage/callers` | Authorized application-subscription/service/model usage summaries |
| `PUT`, `DELETE /portal/{collection}/{id}` | `policies`, `prices`, `assignments`; Function independently enforces Admin |
| `POST /portal/reconciliation/recover` | Explicit Admin cache-recovery operation |

Every APIM client supplies **both** an Entra bearer token and
`Ocp-Apim-Subscription-Key`. Inference tokens target `GATEWAY_CLIENT_AUDIENCE`;
portal tokens target the limiter API audience. APIM validates the tenant/JWT
before reading claims and natively validates the product subscription. All-access
and API-scoped subscriptions are rejected: the provisioned product must contain
the requested API. Do not put keys in URLs.

Application limits, burst counters, discovery and reports use
**`context.Subscription.Id`**, never the key value or Entra user. Primary and
secondary keys, rotation and different users share that app's limits. Keys alone
are not authorization; user tokens alone are insufficient. The Function also
validates registered application/tenant membership. The authenticated principal
remains an audit actor. The portal uses a distinct control-plane product and a
server-only Key Vault-backed key; the browser never receives an APIM key.

Before native burst enforcement, `gateway_caller` traces correlate requests without
raw key values or user identities. Non-secret subscription IDs/application labels
are permitted operational dimensions. The reference algorithm and log joins are
defined in [observability](../docs/observability.md#resolve-a-caller-without-logging-names).

The gateway generates request IDs. It never accepts caller prices, limits, usage
estimates or assumed cached-input discounts. LLM requests reject unknown/unsupported
properties rather than silently dropping their semantics. The gateway preserves supported
fields, pins backend model/API version, limits bodies to 1 MiB, enforces requested output/page
caps, and reserves before dispatch. LLM aliases are resolved exactly as `<api_protocol>:<alias>`
from Terraform's shared `MODEL_REGISTRY`; unknown or wrong-protocol models are rejected before
admission. The request body and reserve keep the client alias for accounting while APIM rewrites
the provider's deployment name before stream payload hashing and upstream dispatch. Each entry
applies its own price pin and token caps, bounded by the Function/gateway global limits. A missing
model uses only an explicitly configured legacy deployment; no additional model becomes an
implicit default. Output caps are positive integers up to each selected model's cap.
Language records use **sum of per-document ceiling(chars/1000)**, not ceiling of a batch.
Each AI route pins the operator's `*_PRICE_VERSION`; caller-supplied catalog versions
are ignored. Publish and validate a catalog version before deploying a route pin to it.

Policy fragments contain only statements, not sections or `<base>`. Native
`rate-limit-by-key` burst protection executes before the external reservation.
Optional `llm-token-limit` is disabled unless Commercial capability has been explicitly
verified; it executes before reservation with a tenant-qualified subscription ID, so native
denials cannot debit the budget ledger. It applies to Chat only, never Responses or Messages.
Unknown prices are rejected by the limiter.

## Trusted streaming relay

With `streaming.enabled=true` (the default), streaming LLM calls reserve first,
then route to a separate managed-identity-protected Function at `POST /api/stream`.
APIM pins the registry selection and forces Chat `stream_options.include_usage=true`; clients may
provide only a boolean `include_usage` in that object. The reserve request includes
`payload_sha256`, the lowercase SHA256 of the exact final UTF8 JSON sent to the relay.
The relay selects the same `protocol:alias` from `MODEL_REGISTRY`, verifies the actual provider
deployment in the rewritten body, and never accepts a caller URL. `STREAM_BACKENDS` remains
available only for legacy runtime compatibility when `MODEL_REGISTRY` is empty.
APIM overwrites reservation/correlation headers, removes caller credentials and provider
headers, drops unmatched query parameters and authenticates to the API audience using
the gateway identity. Nonstreaming dispatch still uses the provider audience.

Streaming remains unbuffered. `X-RateLimit-Admission: conservative` describes admission;
`X-RateLimit-Accounting: provider-stream` identifies the trusted observer, not completed
settlement. `X-RateLimit-Estimated: true` remains conservative when headers are sent,
before terminal provider usage can be observed. APIM never reads streaming response bodies.
Disabling the explicit feature gate restores direct provider streaming and conservative
reservation liability, without deploying the observer or its AI grants.

Known OpenAI latency checkpoints are validated but never counted as billable units.
Responses' zero-valued cache-write counter is accepted; nonzero OpenAI cache writes
remain conservatively reserved until a supported pricing contract is configured.

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
Self-contained message/function-call items may preserve optional nonempty IDs (up to 200
characters) and `status="completed"` from native SDK `response.output`; IDs never replace
required inline content/arguments. Only empty output annotations and output-text `logprobs`
arrays are accepted. Optional text `instructions`, inline function
definitions, `tool_choice`, `parallel_tool_calls`, temperature/top-p and enumerated reasoning
effort are preserved. Sends `store=false` and `background=false`; supplied true values reject.
History IDs, `previous_response_id`, item references, encrypted reasoning, automatic
truncation, media/files and provider-built-in tools are rejected.
This bounded inline subset follows the [Responses REST input schemas](https://learn.microsoft.com/rest/api/microsoft-foundry/azureopenai/responses)
and [SDK input union](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_input_param.py);
preserving an item ID does not enable server-side history lookup.

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
tenant, application subscription, model and reservation. Authenticated users of the
same application can poll; another subscription cannot. Bind failures are fail-closed and
do not leak the backend `Operation-Location`.

Nonstreaming successful JSON response usage is read with `preserveContent: true`.
Only the small backend `usage` object (at most 8192 UTF-8 bytes), never prompt/response
content, is forwarded as `provider_usage`; DI/Language continue sending normalized `usage`.
Known integer counters/details and bounded tier/geography metadata are forwarded; unknown
dimensions or malformed values skip settlement rather than being silently discarded.
Known optional token-detail/cache-creation/server-tool objects may be JSON null and are
forwarded unchanged; null required counters remain conservative, never invented as zero.
Function normalizes Chat/Responses counts or Anthropic uncached + cache-read + both cache-write
TTLs from the reserved protocol. Incomplete counters, unsupported billable dimensions and
ambiguous TTL totals remain conservative; they are never replaced with zero.
An absent OpenAI cached-token count is never fabricated as zero:
the limiter retains estimated cost and the gateway preserves its `data.estimated` flag,
even when settlement returns HTTP 200. Streaming responses are forwarded with
`buffer-response=false` and **never read by outbound policies** (including an unexpected
event-stream response to a nonstream request). The dedicated observer settles complete,
validated provider terminal usage; missing or ambiguous usage, interrupted streams and
the disabled-relay fallback retain worst-case liability until trusted reconciliation or
conservative timer finalization. Transport errors and ambiguous backend errors never auto-refund.
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
