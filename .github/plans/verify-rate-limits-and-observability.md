# Verify live rate limits and observability

Audit the existing public Commercial demo without disabling authentication, resetting
Redis, accepting Claude terms or logging credentials, prompts, document bodies or PII.
Keep infrastructure updates in Terraform and preserve the demo resource tags.

- [x] Audit live Redis state and Application Insights, Log Analytics, APIM and hosting logs.
  Parent owns live queries and evidence under ignored `.azure/publicdemo/`.
  Read-only operator inspection confirms a ready ledger and exact shared request counters:
  Chat + Responses consume two units; denied calls leave the counter unchanged.
  Correlation 5b966a1c-ce3b-47a6-969a-4c26d261a311 joins a Function denial to APIM 429
  with no backend response. Live REDConnectionEvents, StorageTableLogs, FunctionAppLogs,
  AppServiceConsoleLogs, AppTraces, AppEvents and AppDependencies reach the workspace.
- [x] Add comprehensive structured Function decision, settlement, dependency, configuration,
  recovery and error telemetry. Backend agent owns Python source, Function entry point,
  Python dependencies and focused tests; use Microsoft Azure Monitor OpenTelemetry.
  Backend complete: manual safe spans, allowlisted structured exports, bounded
  X-Correlation-ID and Functions invocation trace context. Ruff, mypy (including
  function_app.py), uv build and focused pytest -W error: 90 passed, 1 emulator-only skip.
  Set APPLICATIONINSIGHTS_CONNECTION_STRING and OTEL_SERVICE_NAME=rate-limiter;
  TELEMETRY_ENABLED defaults true (tests disable export). Leave worker auto-init flags
  PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY/PYTHON_ENABLE_OPENTELEMETRY unset/false.
  Optional host.json telemetryMode=OpenTelemetry is parent-owned. SDK batches normally,
  flushes only at shutdown, and cannot replace the durable Table audit on abrupt exit.
  Read-only Redis inspection: hash {limiter}:ledger; ready/recovering/recovering_until,
  c:<debit-key> integer counters, r:<reservation-id> JSON decision/debits/final snapshots.
  accounting.debits(request, policies, price, now) computes debit keys;
  accounting.digest(tenant, principal, request_id) computes reservation IDs.
- [x] Add safe portal server and browser telemetry. Portal agent owns `web/` only:
  request outcomes, API/configuration actions and failures, no token/body/identity logging.
  Implemented structured Node outcomes and manually allowlisted Microsoft browser SDK
  events with cloud-specific endpoint validation/CSP and generated X-Correlation-ID.
  Node 22 lint/typecheck, all 68 tests, production build and production dependency
  audit passed. Runtime settings, schema, privacy limits and delegated MSAL GUI
  harness/selectors are documented in `web/README.md`; parent owns live verification.
  Narrow GUI follow-up reproduced stale root aria-hidden after programmatic dialog
  removal. Added Fluent workspace focus-restoration target; real Chromium checks
  confirm accessible navigation after save, cancel and deletion of the opener row.
- [x] Correct Terraform diagnostic destinations and hosting/APIM telemetry settings.
  Parent owns `infra/`, APIM policies, operator docs and developer automation.
  Provisioned 100% APIM information diagnostics, safe headers/no bodies, Function SDK
  settings, hosting log retention and Redis default-database ConnectionEvents.
  Operator ACL is read-only and must be removed after final Redis inspection.
- [ ] Integrate and validate Python, web, gateway and Terraform changes, then deploy.
  Depends on the three implementation items; require zero-warning Terraform validation,
  warning-free tests and applicable lint/type/build checks.
  Initial integrated provisioning and both application deployments succeeded.
  Live tracing revealed HTTP response codes were exported as zero; corrected standard
  HTTP span attributes and passed 19 focused telemetry tests. Final deployment pending.
- [ ] Configure multiple limits through the authenticated portal and verify allowed/denied
  calls to Chat, Responses, Language and Document Intelligence, counter values and logs.
  Confirm request, cost and service-unit limits, disabled/raised limits, shared protocol
  budgets, actual cached settlement and conservative streaming. Restore test policies.
  Request allow/deny and exact Redis debits verified. GUI create succeeds, but subsequent
  edits are blocked by modal state in the live harness; portal agent is diagnosing.
  Deployed focus fix resolves the modal problem. All 16 authenticated GUI cases pass:
  shared requests 2/4, tokens 1/10000, cost 1/1000000 microUSD, Language records 3/4
  and pages 1/2. Exact Redis counters, raised/disabled policies and GUI deletion pass.
  Cached Redis debit is 1517 microUSD versus 4742 uncached; the monthly counter
  equals the sum of admitted ledger debits (77100). Both SSE formats remain estimated.
  Final audit found duplicate telemetry from Application Insights diagnostics exporting
  back to its own workspace. Removing that unsupported redundant export is pending.
- [ ] Record concrete correlation evidence, destinations, endpoints and limitations.
  Anthropic live verification needs an approved backend. Interactive MFA may require
  the operator; browser automation must disclose any use of an existing delegated token.

Agents work on isolated branches/worktrees, read this plan before coding, run their
focused validation, update their assigned progress and commit only owned files.
The parent integrates deliberately and performs the real-cloud checks.
