# Comprehensive Function rate-limit telemetry

## Findings and scope

Application Insights is already connected through the Microsoft Azure Monitor
OpenTelemetry distro. Live request, decision, budget-status and finalized usage
events exist. Request middleware emits completion logs and server spans. Gaps:
decisions have no explicit inference request/protocol/replay context, replay paths
are silent, budget balances are only emitted when the status page is queried,
unknown accounting reasons are absent, and custom metrics are disabled.

Keep the existing Azure services, public API contracts, durable usage event v2,
enforcement, pricing and idempotency behavior unchanged. Never log raw request or
response bodies, prompts, credentials, user display names or raw Entra identities.
Metrics must exclude per-request, user, subscription and budget identifiers.
Application Insights remains best-effort telemetry, not a financial audit ledger.

## Implementation and validation

- [x] Audit source, exporter configuration and live telemetry delivery.
- [x] Telemetry ownership: `telemetry.py`, `request_telemetry.py`,
  `monitoring.py`, and a focused rate-limit metric component. Add correlated
  operation spans/events and explicit error/replay outcomes; enable manual
  low-cardinality counters/histograms and bounded shutdown flushing.
- [x] Engine ownership: `engine.py`. Record every resolved fresh/replayed decision,
  each evaluated budget's limit/spend/remaining/denial, pinned model/protocol/price
  context, usage replay/conflict/failure, and actual versus unknown usage reasons.
  Tokens are disjoint uncached input/cache reads/output; only newly committed
  actual records contribute tokens/cost metrics.
- [x] HTTP ownership: request completion logs/metrics for successful, rejected,
  malformed, unmatched and failed calls, including route template, method,
  status, elapsed time and trace/correlation context. No raw URLs or query strings.
- [x] Host configuration: disable adaptive sampling in both Function hosts for request
  visibility. Keep worker auto-instrumentation disabled to avoid duplicate/unsafe
  payload, URL and exception capture.
- [x] End-to-end correlation: preserve APIM's existing native W3C correlation
  for `send-request` and backend forwarding; carry the original request ID and
  trace context through the stream Function, provider HTTP call, generator
  iteration, cancellation/final accounting and internal APIM event callback.
  Add regression tests for shared trace IDs and distinct child spans without
  persisting trace context in the financial event schema.
- [x] Tests: extend focused existing tests and add metric/exporter/request tests
  where required. Cover allow/deny, cached tokens, unknown usage, replay/races,
  conflicts/dependency failures, request validation/auth errors, trace correlation
  and privacy. Test metric export using an in-memory SDK reader, not the network.
- [x] Docs: update `docs/observability.md` with the event/metric catalog, sampling
  and tracing semantics, and safe KQL for request/decision/budget/accounting joins.
- [x] Validate strict Python tests, Ruff lint/format and type checks. No frontend or
  Terraform source changes; preserve prior work. APIM callback trace metadata
  additionally validated by the rendered-policy suite and Terraform checks.
- [x] Complete the required Azure preparation validation workflow; local
  implementation is verified, not deployed.
- [x] Record verified outcome and clearly distinguish local changes from deployed
  behavior. No deployment or paid inference calls are part of this request.

## Local validation proof

- `uv run pytest -W error`: 104 passed, one pre-existing skip, no warnings.
- `uv run ruff check .` and `uv run ruff format --check .`: pass.
- `uv run mypy src/ stream/function_app.py`: pass, 35 source files.
- `uv run python -W error -m unittest discover -s apim/tests -v`: 20 passed.
- `terraform -chdir=infra fmt -check -recursive` and
  `terraform -chdir=infra validate`: pass, no errors/warnings.
- `terraform -chdir=infra test -filter=tests/dashboard.tftest.hcl`: two passed.
- In-memory real OpenTelemetry SDK tests prove shared remote trace IDs, distinct
  provider/callback child span IDs, stream close/cancellation cleanup, concurrent
  context isolation, bounded metric dimensions, and no replayed token/cost totals.
- Both documentation correlation queries execute successfully against the live
  linked workspace. All three azd services build/package successfully under Node
  24; the stream wheel and API package contain the new modules and host settings.
- The Azure validation workflow completed with recorded proof. Provisioning was
  previewed only (24 existing in-place updates; no additions/deletions), and no
  deployment or paid inference was performed. Broader drift must be reviewed
  again before a future deployment. Source provider lock restored unchanged.
- Final callback failure metadata accepts only safe correlation IDs, otherwise
  using APIM's transport request ID; the strict gateway suite passes after this
  final hardening. The new telemetry is **locally verified, not deployed**.

## Subsequent deployment

The later request to close the remaining telemetry gaps and deploy all changes
supersedes the local-only status above. The budget and stream Functions and portal
were deployed and verified live on 2026-11-13. Shared W3C operation IDs now include
APIM budget/usage subrequests, stream provider/accounting/callback spans and the
associated decision/usage logs. Actual custom metrics are ingested. See
`close-telemetry-gaps-and-deploy.md` for final validation, accounting and
platform-boundary proof.
