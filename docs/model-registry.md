# Approved OpenAI model registry

`MODEL_REGISTRY` is a JSON map keyed by `protocol:alias`, for example
`openai-chat:sample-model` and `openai-responses:sample-model`. Both hosts use the
same allowlist. An alias identifies a fixed provider deployment and price version;
callers cannot select arbitrary URLs, token audiences or a different billing tier.

Registry records contain protocol, HTTPS endpoint, API path, provider model,
audience, API version, price version and input/output bounds.
See [example registry](../examples/model-registry.json).

APIM creates native backend entities and routes using `backend-id`. Managed
identity authenticates to the configured direct Azure OpenAI account.
The portal's read-only inventory excludes endpoints and credentials.

## Optional backend pools (same model, more endpoints)

An alias can list extra endpoints that serve the **same model** (for example the
same deployment in another Azure OpenAI account or region). Terraform then
creates a native APIM [backend pool](https://learn.microsoft.com/azure/api-management/backends)
for that `protocol:alias`; APIM does the load balancing and circuit breaking, so no
custom failover code exists in the Functions.

Both `MANAGED_MODELS` aliases and `LLM_MODELS` references accept these optional
fields (omit them for today's single-backend behavior):

| Field | Default | Meaning |
|---|---|---|
| `additional_endpoints[].endpoint` | required | HTTPS origin of another account with the same deployment name/model |
| `additional_endpoints[].priority` | `1` | 1 (highest) to 5; lower-priority members only serve when higher ones are unavailable |
| `additional_endpoints[].weight` | `1` | 1 to 100; share among members of the same priority |
| `additional_endpoints[].private_endpoint_verified` | `false` | Must be `true` unless public access is enabled |
| `primary_priority`, `primary_weight` | `1`, `1` | Priority/weight of the primary endpoint (the first pool member) |

```json
{
  "gpt-5.4": {
    "model_name": "gpt-5.4",
    "model_version": "2026-03-05",
    "deployment_sku": "GlobalStandard",
    "deployment_capacity": 10,
    "primary_priority": 1,
    "additional_endpoints": [
      { "endpoint": "https://gpt54-westus3.openai.azure.com", "priority": 1, "weight": 1, "private_endpoint_verified": false },
      { "endpoint": "https://gpt54-standby.openai.azure.com", "priority": 2, "private_endpoint_verified": false }
    ],
    "protocols": { "openai-chat": { "...": "unchanged" } }
  }
}
```

How it behaves:

- The primary endpoint (managed alias: the Foundry/OpenAI account; reference:
  `endpoint`) is member `m0`. Each member is a native APIM backend named
  `ai-model-<hash>-m<n>` with a **circuit breaker**: three 429/5xx responses in one
  minute (`gateway.backend_circuit_breaker`) open it for one minute, and a
  `Retry-After` header is honored.
- The pool is `ai-pool-<hash>`; the policy sets this ID for pooled aliases and the
  same `ai-model-<hash>` ID for single-endpoint aliases, which are unchanged. The
  hash is `sha256("<protocol>:<alias>")`, as before.
- For non-streaming requests the policy retries up to twice on 429/5xx so the pool
  can try another member. Admission, budget checks and usage recording run once
  outside that retry, so a retried request is charged once, from the final response.
- **Streaming is not pooled.** Streaming requests go through the Function relay,
  which calls the primary endpoint directly; the circuit breaker and retry do not
  protect them. Run a pooled alias only where this is acceptable.
- Every member shares the alias's audience, API version, deployment path and price
  version. The deployment name (managed: the alias) must exist on each extra
  account. Cost accounting stays per model; a pool never changes pricing.
- Terraform does **not** grant RBAC on additional accounts. Give the APIM gateway
  identity `Cognitive Services OpenAI User` (or the alias's role) on each one.
- `MODEL_REGISTRY` given to the Functions keeps its shape; pool fields are stripped.

When adding a model:

1. Verify the model/deployment, region, cloud and available quota.
2. Configure its alias/protocol and supported text-only request bounds.
3. Add a versioned price card with uncached input, cached input and output USD
   rates per million tokens. Sample prices are not current retail quotes.
4. Validate non-streaming and streaming usage, including cached-input details.
5. Apply the reviewed Terraform/azd change and verify the shared dashboard.

No separate provider implementation or model-specific APIM budget arithmetic is
needed. Newly billed modalities or server tools are not automatically supported
by a text-only price card. Government endpoints/audiences must be independently
verified; do not silently fall back to Commercial.
