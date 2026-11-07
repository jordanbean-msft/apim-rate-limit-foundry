# Application subscriptions, supported runtime and portal refresh

## Contract and safety boundaries

- Require both Entra JWTs and validated product-scoped APIM subscription keys.
  Identify applications by `context.Subscription.Id`, never the key value.
  Both keys and rotated keys share limits. Preserve Entra principal IDs only as
  authenticated actor/audit metadata, not budget counter identities.
- Policy `subscription_id` is explicit (`"*"` for intentionally shared templates);
  Assignment binds `tenant_id`, `subscription_id`, `policy_ids`, optional
  `display_label` and `reader_principal_ids`. Reader access to app data requires
  an explicit assignment; Admin retains administration. Do not silently widen
  old per-user policies or expose another application's data.
- Reserve requires `subscription_id`; retain `principal_id` as actor metadata.
  Rollups expose `subscription_id` instead of principal identity. Keep `/usage/callers`
  compatible as the subscription-report route, with privacy-safe `caller_ref`
  derived from tenant + subscription ID. No raw keys in telemetry/storage/UI.
- Protect every APIM API, including `/portal`, with product subscriptions.
  The portal uses a same-origin Node proxy and a server-only subscription key
  supplied through a managed-identity Key Vault reference. Browser requests use
  the native sign-in cookie plus `X-Portal-Access-Token`; proxy forwards the
  delegated token as Authorization and adds the key. Never expose the key.
- Move App Service to a currently available supported Node LTS (24). Deploy at
  least three actual available Foundry deployments with distinct aliases/prices,
  preferably current GPT general/mini/nano variants after checking quota/catalog.
  Preserve the existing account/deployment while removing sample aliases from
  active portal routing. No Marketplace acceptance or unreviewed replacements.

## Ownership and acceptance

- [x] Backend/APIM implementation (accounting agent and main agent), integrated:
  application selection/counters,
  replay/stream/document ownership, explicit Reader scoping, telemetry and KQL,
  migration/seeding, example and operator documentation. Preserve
  trusted cached-token settlement. Add focused cross-user/same-subscription and
  cross-subscription isolation/rotation tests. Worker strict Python suite:
  184 passed, 8 optional skips; APIM policy/seed tests: 37 passed.
- [x] Portal implementation (isolated frontend agent; `web/**`), integrated:
  application-oriented DTOs,
  editors/reports/filters, native-cookie safe same-origin proxy, Graph own-photo
  with scoped token/fallback/revocation, exact `Howdy <name>!` greeting; restrained
  single-font, square-edged, accessible Fluent styling. No browser secrets or
  profile/photo telemetry. Worker 94 tests/lint/types/build/format passed.
  Parent replaced universal CSS overrides with native Fluent theme tokens and
  direct square-edged styles; combined validation passed.
- [x] Infrastructure (isolated infra agent; owns `infra/**` except
  `infra/modules/monitoring/**`, plus `azure.yaml`/VS Code runtime automation):
  Node 24, Graph delegated User.Read consent, managed model deployments/catalog,
  APIM products/subscriptions/required keys, Key Vault reference/identity/roles,
  runtime APPLICATION_REGISTRY and safe metadata outputs. Mock cloud tests,
  recursive fmt, zero-warning validate and TFLint: 33 Terraform tests passed in
  worker. Reviewed Azure provision completed: 21 creates, 19 in-place updates,
  zero deletes; three real deployments, product subscriptions, vault and Node 24.
- [x] Finish regenerated architecture previews and combined validation.
  All three SVG previews regenerated from editable sources. Combined strict
  Python/APIM/frontend/Terraform validation: 184/37/94/33 passed (8 optional
  Python integration skips); lint, types, builds, formatting and hooks passed.
- [x] Integrate isolated worktree patches deliberately; update docs and checked
  items from verified outcomes. Validate combined code and deployment workflow.
  All three task-only patches integrated, preserving the dirty baseline.
- [x] Review actual Azure plan; provision/deploy through azd, preserving unrelated
  P1v2/main/web Always On drift. Migrate existing configuration deliberately,
  back up old records and do not silently relabel historical user usage.
  Provision and all three service deployments succeeded. Protected
  backups contain all 799 old Table entities and remote Terraform state.
  Published three retail-verified LLM price cards, 12 explicit app policies and
  two Reader assignments; retired only the two invented Foundry price cards
  through audited soft deletes. Legacy history/counters were not relabeled.
- [x] Verify missing key/token and invalid key rejection, both keys sharing limits,
  separate subscriptions isolated, actual Chat/Responses/streaming with multiple
  deployed models and cache-aware settlement, populated subscription dashboards,
  supported live runtime, protected portal/proxy and Graph permission setup.
  Record interactive sign-in/Graph-photo/Government/private-network limitations.
  Actual acceptance: 26 LLM requests (24 successes and two intentional 429s),
  all three models through both protocols and SSE; primary/secondary keys share
  limits and application B stays isolated under the same actor. Actual provider
  usage settled correctly, including 4,864 cached tokens. An initially shorter
  cache probe produced no hit; only the cache probe was resumed with a longer
  prefix, without reseeding or resetting budgets. Language and Document
  Intelligence share application A's key; secondary-key document polling works,
  while application B receives 404. Seven invalid authentication combinations,
  including the existing all-access key without a product, return 401.
  All 22 live KQL queries passed; application/model costs, limits and denials
  are populated, including the final cache-hit telemetry. Native Node 24,
  resolved managed-identity vault reference, least-privilege Graph User.Read
  consent, gateway roles and unchanged P1v2/Always On settings were verified.
  Browser-style requests redirect to Entra; anonymous programmatic requests and
  direct Function calls return 401. Interactive MFA/photo retrieval and live
  Government/private-network/Anthropic deployments remain unverified, not
  bypassed or represented as certified. The refreshed layout was browser-tested
  locally with explicitly identified fixture data.
