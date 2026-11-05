# Gateway surface and supported bounds

Terraform creates explicit APIM operations; there are no catch-all backend routes.
Only enabled AI services are published. The portal API is always published.

| Route | Request / accounting model |
|---|---|
| `POST /foundry/chat/completions` | JSON `messages` with text-only system/user/assistant content, mandatory `max_tokens` 1–4096, optional Boolean `stream`; model is the configured deployment alias |
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
estimates or assumed cached-input discounts. It strips unsupported request properties,
pins backend model/API version, limits bodies to 1 MiB, enforces requested output/page
caps, and reserves before dispatch. Foundry conservative input estimates use UTF-8 bytes
plus framing overhead and support text-only OpenAI byte-tokenized deployments; do not
configure arbitrary non-OpenAI tokenizers and claim hard token bounds.
Language records use **sum of per-document ceiling(chars/1000)**, not ceiling of a batch.
Each AI route pins the operator's `*_PRICE_VERSION`; caller-supplied catalog versions
are ignored. Publish and validate a catalog version before deploying a route pin to it.

Policy fragments contain only statements, not sections or `<base>`. Native
`rate-limit-by-key` burst protection executes before the external reservation.
Optional `llm-token-limit` is disabled unless Commercial capability has been explicitly
verified; it executes before reservation with a tenant-qualified principal key, so native
denials cannot debit the budget ledger. Unknown prices are rejected by the limiter.

Limiter backend URLs are exactly `/api/decisions/reserve`, `/settle`, `/release` under
`/api/decisions` (release is intentionally **not** invoked by these policies).
Trusted operation binding/checking calls are `/api/operations/bind` and `/check` under
`/api/operations`, using the gateway application role. Document owner metadata includes
tenant, canonical principal, model and reservation. Bind failures are fail-closed and
do not leak the backend `Operation-Location`.

Nonstreaming response usage is read with `preserveContent: true` and settles actual
prompt/output/cached tokens. An absent cached-token count is never fabricated as zero:
the limiter retains estimated cost and the gateway preserves its `data.estimated` flag,
even when settlement returns HTTP 200. Streaming responses are forwarded with
`buffer-response=false` and **never read by outbound policies**; their worst-case
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
