# Close telemetry gaps and deploy

- [x] Parent: diagnose APIM's missing Application Insights delivery and implement
  the smallest durable configuration/policy fix with offline validation and live
  proof. Own `infra/`, `apim/`, deployment orchestration and integration docs.
  Configuration ready: component-scoped managed ingestion, regional connection
  string, create-before-destroy logger cutover and correlated enqueue events.
  Seventeen Terraform tests passed. Provisioning completed; a real read-only
  APIM-to-Function request now produces APIM SDK requests/dependencies and linked
  host/manual Function records under the same W3C operation ID. The old
  instrumentation key matched; its historical delivery failure is not presented
  as a proven key/configuration corruption.
- [x] Portal agent: isolated worktree; own `web/` telemetry, server/proxy/browser
  correlation and focused tests. Export structured server logs and dependency
  traces to App Insights using Microsoft tooling; keep strict privacy allowlists
  and existing API/UX behavior. Validate Node 24 tests/lint/typecheck/build.
  Integrated baseline-relative patch; 116 tests, lint, typecheck and build passed.
  Explicit native-agent disablement and production-dependency packaging added
  by parent. Package/build proof still belongs to the integration step below.
- [x] Python agent: isolated worktree; own `src/` and focused Python tests for
  dashboard ARM/Log Analytics, managed identity and Redis lock dependency spans;
  observe callback acceptance/failures safely. Preserve the existing pending
  telemetry, financial schemas/idempotency and error semantics. Validate uv
  strict focused tests, Ruff and mypy. Integrated baseline-relative patch;
  124 strict Python tests passed, one optional Azurite skip; Ruff lint/format and
  mypy passed. No runtime configuration or accounting schema changes.
- [x] Parent, after both agents: integrate only owned changes, run combined strict
  Python/gateway/web/infra checks, and update observability documentation with
  actual coverage and intentional platform/provider/downstream boundaries.
  Final portal ZIP contents verified after correcting azd's default
  `node_modules` exclusion with a staged `.webappignore`.
- [x] Parent, after integration: complete Azure validation workflow with fresh
  preview/package and static RBAC proof; use azure-deploy to provision/deploy all
  services in the existing environment. No unrelated resource replacements.
  All three applications deployed; incremental policy provisioning succeeded
  after a second completed validation workflow, with no creates or deletes.
- [x] Parent, after deployment: verify live APIM/portal/Function telemetry and
  shared W3C IDs, including provider/callback and SSE where applicable. Verify
  Event Hub acceptance and distinguish it from consumer processing; preserve
  budgets and avoid unbounded inference load.
  Live ordinary/SSE calls share native APIM and Function operation IDs and
  reconcile exactly once to provider usage. Existing exhausted-budget denial
  returns 429 without charging. Two new broker messages are confirmed; all 16
  dashboard tiles return without query errors. Budget configurations unchanged.
- [x] Parent follow-up from live proof: explicitly retain incoming `traceparent`
  on APIM's budget/usage `send-request` calls, then validate/preview/provision the
  policy-only fix and verify the traced inference operation includes those
  Function invocations. Preserve request-ID fallback for uninstrumented clients;
  do not synthesize an APIM span ID that policy expressions cannot observe.
  Regression contracts and live operation grouping pass for normal, streaming
  and denied requests, including budget/usage subrequests and stream callbacks.
- [x] Parent: record final deployed evidence, any genuine platform limitations,
  and stop temporary verification helpers. Do not mark complete before live
  verification or an explicitly documented blocker.
  Evidence is retained in session `close-gaps-*` artifacts and the local
  deployment plan. Temporary SSH probes stopped; both integrated task-owned
  worktrees removed. Existing unrelated worktrees and changes are preserved.

## Final proof

Deployment and verification completed on 2026-11-13. Source validation: 124 strict
Python tests (one optional Azurite skip), 116 Node 24 tests, 21 gateway contracts
and 17 Terraform tests; configured lint, formatting, type and build checks pass.
The four minimal successful inference probes cost 168 micro-USD in total; each
matches exactly one actual ledger record. The final denied probe incurred no
provider charge or usage record. APIM enqueue IDs and stream acceptance IDs
agree; broker ingress is verified separately, not misreported as consumer success.

Portal-server, APIM, host/manual Function and dashboard dependency telemetry was
verified live. Browser SDK/privacy/correlation behavior is covered by local
tests; no new interactive browser sign-in/consent was performed. Native
platform/authentication logs remain in their supported workspace destinations.
Uninstrumented callers retain request-ID joins rather than a fabricated native
APIM W3C parent. These intentional boundaries are documented in
`docs/observability.md`.
