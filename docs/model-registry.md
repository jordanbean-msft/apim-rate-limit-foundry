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
