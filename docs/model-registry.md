# Model registry

The deployed allowlist maps `<protocol>:<alias>` to a fixed approved backend.
Clients send the **alias** in the existing Chat (`/foundry/chat/completions`),
Responses (`/foundry/responses`) or Messages (`/anthropic/v1/messages`) body.
The actual provider deployment may have a different name. The same alias can
appear in Chat and Responses; protocol comes from the route. An unknown alias
or wrong protocol fails before reservation or dispatch, not at an arbitrary
client-selected URL. Legacy routes retain a missing-model default only where
previously configured.
Shared aliases use the same policy selectors across those protocols; each
registry entry can nevertheless pin a different price version for that alias.
Adding a deployment with an existing supported API and billing contract is
configuration-only. New protocols, billable tools, modalities or pricing tiers
need explicit normalization/pricing support; a new model name does not enable them.

## Add or change a model

1. Approve an existing backend for the selected cloud, region, API, model and
   network; verify capability and bounds, and grant the gateway/stream
   identities the required backend RBAC. Referenced deployments are not created
   by the registry. Government never falls back to Commercial; unsupported
   Government Claude/Messages remains disabled.
   For Messages, `max_input_tokens` must be the verified full backend input
   ceiling, not a preferred application limit; every call reserves that ceiling.
2. Add the entry to Terraform `llm_models`, keyed by `<api_protocol>:<alias>`.
   Set azd `LLM_MODELS` to the corresponding JSON object (`{}` by default).
   See the [infrastructure reference](../infra/README.md) for the complete
   required fields and protocol-specific verification gates. Existing singular
   configuration remains supported; registry entries expand it.
3. Publish one matching Foundry price card for the **alias** and pinned
   `price_version`, including all required cache-write rates for Messages.
   The examples contain invented prices, not provider quotes. Add model-specific
   policies if needed; a wildcard model `*` cost policy pools that application's usage
   across models/protocols while matching model rules also apply. Summaries
   count spend once even when several policies are debited.
4. Run `azd provision` then `azd deploy`; test discovery, allowed and rejected
   aliases, prices and policy outcomes. No per-model policy branch is needed.
   Change a registry price pin through Terraform and provision/deploy, not just
   by editing the portal price catalog. In-flight requests retain their pinned
   prices. Preserve old versions for existing history and outstanding calls.

The portal's read-only **Model inventory** displays each protocol/alias, provider
deployment, token caps and price pin; Admin and Reader may discover it. The
API exposes no backend endpoint or audience. A missing, ambiguous or unavailable
price is not free, and a visible price is not proof of successful admission.
Policies and prices remain editable by Admin; model suggestions use aliases,
not provider deployment names. Manual service model entry remains available.
Legacy environments with no registry return an empty list. Failed discovery
is shown as an error, never replaced with sample models.

## Managed real deployments

The managed Foundry deployment map provisions actual approved model deployments
and derives the same Chat/Responses registry used by APIM, both Functions and the
portal. It is not a list of cosmetic sample aliases. The legacy deployment can
remain in Azure to avoid destructive migration without being advertised as a
current model. Referenced `LLM_MODELS` still supports other approved accounts and
protocols; adding a supported model needs no hand-written per-model policy branch.

For the Commercial Global Standard text baseline, verified Azure public retail
prices per million tokens are:

| Model | Input USD | Cached input USD | Output USD |
| --- | ---: | ---: | ---: |
| GPT-5.4 (below 272k context) | 2.50 | 0.25 | 15.00 |
| GPT-5.4 mini | 0.75 | 0.075 | 4.50 |
| GPT-5.4 nano | 0.20 | 0.02 | 1.25 |

Source: [Azure Retail Prices API](https://prices.azure.com/api/retail/prices?%24filter=armRegionName%20eq%20%27eastus2%27%20and%20contains(skuName,%275.4%27)),
`Foundry Models` / `Azure OpenAI GPT5`, East US 2 Global non-Batch/non-priority
meters, effective March 1, 2026; checked November 6, 2026. These are public USD
reference rates, not negotiated invoice or Government prices. Pin a reviewed
version and keep the configured GPT-5.4 context/output bounds below the
long-context pricing threshold. Unsupported tiers, explicit paid extended cache
writes and other billable dimensions remain rejected or conservatively held.
The generic files in `examples/` still contain deliberately illustrative prices.

## Local configuration example

[`examples/model-registry.json`](../examples/model-registry.json) contains two
aliases per protocol and a shared Chat/Responses alias. It uses placeholder
HTTPS origins and deployment names, so it cannot make live calls as supplied.
This fixture is Commercial-only. For Government, omit Messages and use verified
sovereign origins (for example `https://example.openai.azure.us`) with the
`https://cognitiveservices.azure.us` audience; availability still needs verification.
For local API discovery, set the runtime variable before starting the API:

```bash
export MODEL_REGISTRY="$(cat examples/model-registry.json)"
uv run apim-rate-limit-foundry
```

For actual inference replace the placeholders with approved, reachable origins,
paths, deployment names, audience, versions and verified limits, and use the
real stores/credentials required by the gateway and streaming host. Never put
secrets in this file. `MODEL_REGISTRY` entries carry `api_protocol`, `endpoint`,
`path`, provider `model`, `audience`, `api_version`, `anthropic_version`,
`price_version`, `max_input_tokens` and `max_output_tokens`. Terraform generates
this runtime registry from deployment configuration; don't edit deployed
Function settings independently. `STREAM_BACKENDS` remains a legacy path.
See [local development](local-development.md) for host and store limitations.

[`examples/gateway.http`](../examples/gateway.http), [prices](../examples/prices.json)
and [policies](../examples/policies.json) demonstrate the aliases and pooled
budget. Protocol-specific usage normalizers and conservative reserve/settle
accounting are unchanged: periods are UTC calendar windows, not sliding windows
or token buckets. Every call also needs Entra authorization and an inference
product subscription key; the stable subscription ID owns the shared app budget.
