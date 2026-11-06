# Verify live rate limits and observability

Audit the existing public Commercial demo without disabling authentication, resetting
Redis, accepting Claude terms or logging credentials, prompts, document bodies or PII.
Keep infrastructure updates in Terraform and preserve the demo resource tags.

- [ ] Audit live Redis state and Application Insights, Log Analytics, APIM and hosting logs.
  Parent owns live queries and evidence under ignored `.azure/publicdemo/`.
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
- [ ] Correct Terraform diagnostic destinations and hosting/APIM telemetry settings.
  Parent owns `infra/`, APIM policies, operator docs and developer automation.
- [ ] Integrate and validate Python, web, gateway and Terraform changes, then deploy.
  Depends on the three implementation items; require zero-warning Terraform validation,
  warning-free tests and applicable lint/type/build checks.
- [ ] Configure multiple limits through the authenticated portal and verify allowed/denied
  calls to Chat, Responses, Language and Document Intelligence, counter values and logs.
  Confirm request, cost and service-unit limits, disabled/raised limits, shared protocol
  budgets, actual cached settlement and conservative streaming. Restore test policies.
- [ ] Record concrete correlation evidence, destinations, endpoints and limitations.
  Anthropic live verification needs an approved backend. Interactive MFA may require
  the operator; browser automation must disclose any use of an existing delegated token.

Agents work on isolated branches/worktrees, read this plan before coding, run their
focused validation, update their assigned progress and commit only owned files.
The parent integrates deliberately and performs the real-cloud checks.
