# Building the cross-cloud AI rate-limiting sample

The approved detailed plan is the session's `plan.md`. This checklist tracks execution.
No live Azure resources are provisioned without operator configuration and credentials.

- [ ] Backend: Python Functions app, domain contracts, accounting, atomic Redis storage,
  durable Table storage, reconciliation, auth, focused Python tests.
  Ownership: `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `function_app.py`, `host.json`.
  Initial implementation integrated and passed Ruff/mypy and 40 combined tests.
  Follow-up: local Functions-host detection, model-module boundaries, denial metadata,
  period/metric counter keys, local persistent-store support, and accounting audit details.
- [ ] Gateway/infrastructure: APIM XML and OpenAPI, Terraform modules, cloud-aware azd
  provisioning inputs, managed identity, networking, diagnostics.
  Ownership: `apim/`, `infra/`, `azure.yaml`.
  Integrated; Terraform validates with zero errors/warnings, three mocked cross-cloud plans
  and seven initial policy contract tests pass. Native-limit ordering and recursive
  TFLint fixes integrated; final combined validation pending.
- [ ] Portal: Fluent UI React v9, MSAL, administrator CRUD, consumer observability.
  Ownership: `web/`.
  Integrated; lint/typecheck, 25 tests and production build pass.
  Follow-up: newly introduced development-tool dependency advisories.
- [ ] Integration: align wire contracts, local seed/sample requests, deployment packaging,
  VS Code tasks/debuggers, CI, user docs and architecture.
  Ownership: remaining files and integration fixes after worktree merges.
  Depends on the three workstreams.
  Seed and three-service HTTP smoke passed, including cached settlement and reader isolation.
  Actual Azure Tables SDK/Azurite transactions and immutable events verified.
- [ ] Final validation: combined Python/frontend/infrastructure checks and local workflow
  smoke tests. Document unavailable live-cloud checks rather than claiming deployment.

## Shared wire contracts

- Function API base: `/api`. Routes: `/health`, `/decisions/reserve`,
  `/decisions/settle`, `/decisions/release`, `/policies`, `/prices`, `/assignments`,
  `/usage`, `/audit`, `/reconciliation`.
- Authentication: Function App Easy Auth validates Entra tokens; application code checks trusted
  principal roles/claims, APIM workload role `RateLimit.Gateway`, admin `RateLimit.Admin`,
  reader `RateLimit.Reader`. Local auth bypass must be explicitly enabled and rejected in Azure.
- Reserve: `{request_id, principal_id, tenant_id, subscription_id?, service, model,
  operation, usage: {input_tokens, output_tokens, cached_input_tokens, pages,
  text_records, requests}, streaming}`. Service names: `foundry`, `document-intelligence`,
  `language`. `request_id` is gateway-generated, never trusted from the caller.
- Decision: `{allowed, reservation_id?, reason, remaining, retry_after, reset_at,
  estimated, headers}`. Budget values are integer micro-USD, not floating point.
- Settle: `{reservation_id, usage: {...}, status: "actual" | "conservative"}`.
  Release: `{reservation_id}`. These are trusted gateway-only APIs.
- Policies: `{id, name, service, model: "*", principal_id: "*", limit,
  period: "minute" | "hour" | "day" | "month", metric: "cost" | "tokens" |
  "requests" | "pages" | "text_records", enabled, priority}`.
- Prices: `{id, service, model, version, input_per_million, output_per_million,
  cached_input_per_million, per_page, per_text_record, per_request}`.
  Prices are decimal USD strings; calculations convert to integer micro-USD conservatively.
- Assignments: `{id, principal_id, policy_ids}`. Identity keys include tenant boundaries.
- CRUD: GET collection returns JSON array; PUT `/{id}` saves a typed record;
  DELETE `/{id}` removes it. GET `/usage` and `/audit` return arrays of scoped records.
- Never send model prompts, document contents, bearer tokens or subscription keys to telemetry
  or the limiter. Use APIM subscription IDs, not subscription secret values.

## Correctness gates

- Conservative admission does not assume cached hits in advance; settle actual cached usage later.
- Denied requests do not debit budgets. Concurrent and retried reservations are atomic/idempotent.
- Redis loss must fail closed until recovery; do not silently initialize budgets from zero.
- Streaming without trusted actual usage retains its conservative debit; expiry is not a refund.
- Document Intelligence polling must remain behind APIM; `Operation-Location` must be rewritten
  and operation IDs bound to the submitting principal.
- Explicitly bound input/output/page sizes; do not claim a hard spend cap from an unbounded estimate.
- No unsupported cloud or tier silently falls back to another cloud or public networking.
