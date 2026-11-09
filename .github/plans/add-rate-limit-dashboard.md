# Rate-limit custom traces and Azure dashboard

Expose privacy-safe rate-limiter outcomes as custom traces and deploy a shared
Azure portal dashboard through the existing Terraform/azd workflow. Preserve
Commercial/Government compatibility, authentication and all accounting behavior.

- [x] Extend decision and per-policy traces with stable event/version identifiers,
  conservative liability, policy evaluation outcomes and actual/refunded settlement
  information. Parent owns Python source, focused tests and telemetry documentation.
  Acceptance: no payloads/identities/keys; replay-aware queries; strict tests/lint/types.
  Additive schema implemented: event_name/version, requested vs applied debits,
  allowed/denied/blocked policy outcomes and original/refunded settlement liability.
  116 strict Python tests pass (eight optional skips), 38 focused telemetry/engine
  tests pass, mypy (41 files), Ruff/format, hooks and package build pass.
- [x] Build a shared Azure portal dashboard using workspace log-query tiles for
  allow/deny, APIM 429 origin, per-policy pressure, settlement/cache usage, latency
  and dependency failures. Dashboard agent owns `infra/`, focused Terraform tests
  and operator documentation. No duplicate Insights diagnostic export.
  Acceptance: cloud-aware portal URL/output, tagged resources, valid JSON/KQL,
  Terraform format/validate/plans with no warnings.
  Integrated dashboard and eight reusable KQL queries; 16 mocked Terraform tests,
  recursive format/validate and TFLint/hooks pass. Both cloud URLs tested.
- [x] Integrate code and infrastructure, run relevant combined validation, preview
  no unintended deletion, deploy through azd. Depends on both implementation items.
  Monitoring-scoped provisioning added only dashboard/name (two additions, zero
  changes/deletions); API-only deployment succeeded. Existing P1v2 plans and
  disabled Always On were preserved rather than reverting unrelated live drift.
- [x] Generate representative allowed/denied/settled calls; verify new custom
  properties and every dashboard query against live workspace data; verify the
  persisted dashboard resource and portal rendering when available. Remove only
  task-created test policies. Depends on deployment.
  Live smoke passed Chat, Responses, both SSE formats, cached settlement, Language,
  PDF polling, custom 429 and durable recovery. All eight queries from the persisted
  tagged dashboard executed successfully; 22 fresh custom traces verified versioned
  schema, denied/blocked zero debits and settlement refunds. No dependency failures
  observed. Workload RBAC and sole Function Redis assignment verified unchanged.
  Azure portal browser rendering requires interactive sign-in and was not verified;
  ARM persistence and actual workspace query execution were verified instead.
- [x] Record dashboard link, verification evidence and limitations. Depends on
  live verification.
  Dashboard: use the deployment's `AZURE_DASHBOARD_URL` azd environment output.
  Evidence: ignored `.azure/publicdemo/rate-dashboard-evidence.json`, provision log
  and refreshed smoke results. Telemetry has ingestion/windowing limitations and
  is not billing/accounting truth. Government compatibility is structurally tested,
  not deployed live; Anthropic remains disabled pending an approved backend.

Work in isolated worktrees for parallel changes. Update assigned progress only
after implementation and specified validation pass.
