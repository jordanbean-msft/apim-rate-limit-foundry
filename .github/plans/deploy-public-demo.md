# Deploy public-network demo

The user explicitly requested public networking and `SecurityControl=Ignore`.
Keep managed identity, TLS, authentication and authorization enabled.

- [x] Prepare an isolated Commercial `publicdemo` environment and supported region.
  Use the authenticated demo subscription; never change unrelated resources.
- [x] Apply the tag to every taggable solution resource and remote-state resources.
  `infra/main.tfvars.json` records this explicitly requested demo exemption.
  Live inventory verifies all 16 application resources, both resource groups and the
  state account, including the automatically created smart-detector alert.
- [x] Validate configuration, Terraform, packages, quotas and deployment identities.
  Twelve mocked plans, 20 gateway tests, warning-free Terraform validation, both azd
  packages and a real 102-resource creation preview passed. Live provisioning exposed
  strict SPA root-URI validation; canonical trailing-slash redirect now passes.
- [x] Provision with azd using Entra-authenticated Azure Blob remote state.
  Baseline provisioning completed successfully without recreating the gateway.
  Corrected reserved Function settings and a retired model selection. Preserved the
  existing gateway by migrating its Terraform ownership to AzAPI's ARM service resource,
  avoiding AzureRM's unsupported direct-management API read. Recovery preview:
  56 additions, one in-place change, zero destructions; 12 mocked plans pass.
- [x] Deploy Functions and the React portal; configure models, roles, prices and policies.
  Functions package deployed successfully; HTTP and timer entry points are indexed.
  Explicit approved-client Easy Auth configuration resolves live 403s without disabling
  authentication. Admin CRUD, four prices, six policies, Table persistence and Managed
  Redis recovery work. Anonymous/forged-principal requests return 401. Actual GPT-5.4-mini
  direct Chat and Responses inference both return 200. Both application packages are
  deployed. Incremental provisioning completed, enabling the Responses gateway route
  and forwarding verified nonbilling provider metadata for actual OpenAI settlement.
  Final `azd deploy` completed successfully for both apps after provisioning.
- [x] Verify live portal and APIM paths, actual settlement, streaming and denials.
  Live browser checks verify the Fluent app, real configuration, CORS and Entra sign-in
  redirect. Authenticated admin APIs work. APIM Chat inference, Language settlement and
  one-page PDF submission/polling/actual settlement pass. The complete final smoke also
  verifies Chat and Responses actual settlement, both SSE routes, rejected stateful
  Responses requests, Function-driven custom 429 and removal of its temporary policy.
  A real cache hit reports 1,792 cached tokens out of 2,355 input tokens; independent
  decimal arithmetic matches durable discounted settlement (1,517 micro-USD versus
  4,742 without caching, both with four output tokens). These are illustrative prices.
  Interactive portal sign-in/MFA is not verified and remains operator-owned.
- [x] Record endpoints, evidence, limitations and any provider-availability blockers.
  Commercial East US 2 deployment, environment `publicdemo`, model `sample-model`
  (GPT-5.4-mini, version `2026-03-17`). Portal and gateway endpoints are available
  through the deployment's `WEB_URL` and `GATEWAY_URL` azd environment outputs.
  Authenticated admin APIs, durable summaries, live RBAC, Redis recovery and
  Application Insights HTTP/timer telemetry pass. `azd show` discovers both apps after
  tagging the pre-created application group with `azd-env-name=publicdemo`.
  Ignored local evidence is under `.azure/publicdemo/`: final provisioning/deployment
  logs, `smoke-results.json`, `portal-results.json` and the sign-in screenshot.
  Anthropic remains disabled: no approved Claude backend/provider terms are available.
  Government portability is implemented but this task deployed Commercial only.

Validation includes Terraform fmt/validate/test, APIM tests, live role/tag inventory and
real HTTP requests. Do not equate mocked tests with service-side policy compilation.
Anthropic enablement requires an available approved deployment and must not silently
accept Marketplace terms or substitute another protocol/provider.

Current recovery validation: 12 mocked Terraform plans (including shared managed-account
role reuse), zero-diagnostic Terraform validation, changed-file hooks and TFLint pass.
The automatically created Application Insights smart-detector alert was also tagged.
Strict Python tests: 95 passed, eight optional integration skips; Ruff, mypy and package
build pass. Known OpenAI latency metadata and zero Responses cache-write counters now
settle safely; unknown or unpriced usage dimensions remain conservative.
