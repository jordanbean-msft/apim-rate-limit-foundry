# Show APIM gateway and Function accounting charts

## Findings and invariant

The deployed Terraform dashboard defines every tile as `AnalyticsGrid`, without
`SpecificChart` or `Dimensions`. The portal correctly interprets these as tables,
so existing chart components never receive chart metadata.

The persisted Azure dashboard remains the single KQL/visualization source. Keep
workspace telemetry Admin-only and preserve Reader-scoped ledger reports. Provider
cached input is a subset of input. Budget-blocked requests have no provider token
usage and must be charted as requests, never invented "blocked tokens".

## Implementation

- [x] Trace persisted dashboard metadata, chart rendering and live telemetry schema.
- [x] Select the dashboard design under autonomous continuation. This does not
  constitute approval for unrelated infrastructure changes.
- [x] Infrastructure ownership: `infra/modules/monitoring/main.tf`, its KQL queries,
  and `infra/tests/dashboard.tftest.hcl`. Define actual chart metadata and axes;
  cover APIM traffic/outcomes, model admission, disjoint token composition and
  trends, cache-hit percentage, spend, Function accounting outcomes, check/record
  latency, Table/Redis dependency health and budget utilization.
- [x] Portal ownership: `web/src/components/Dashboard.tsx`, contracts only if needed,
  and existing dashboard tests. Put charts before drill-down grids and explain
  admission versus completion, blocked requests, cache meaning and telemetry gaps.
- [x] API/test ownership: dashboard parser tests in `tests/test_dashboard.py`;
  preserve fixed-workspace KQL and exercise chart metadata from the actual catalog.
- [x] Documentation: update `docs/observability.md` with metric definitions, sources,
  chart navigation and interpretation of unknown or incomplete accounting.
- [x] Validate: focused portal tests, ESLint, TypeScript/build, Prettier; strict
  Python dashboard tests/lint if changed; Terraform fmt/validate with zero warnings
  and focused dashboard tests; execute every changed KQL against live telemetry.
- [x] Publish reviewed dashboard metadata through azd and deploy web; verify the
  live API returns chart types/axes and actual nonempty chart series. User requested
  deployment after disclosure of the accompanying updates. Broader preview
  reviewed, validation workflow completed, provisioning and portal deployment pass.

## Validation evidence

- Portal: 29 focused tests pass; ESLint, TypeScript/production build and changed
  file Prettier checks pass.
- API contract: nine Python dashboard tests pass with warnings as errors; Ruff
  lint and format checks pass.
- Terraform: fmt checks and validation pass with zero errors/warnings; both
  dashboard catalog tests pass, including missing-axis rejection.
- All 16 persisted KQL queries return live telemetry without errors.
- Real Chromium desktop (1440px) and mobile (390px) verification renders all ten
  charts and six grids from the planned metadata and collected live query rows.
  No browser errors or undefined legends. Screenshots/evidence are session-only.
- Browser helper stopped and temporary harness removed. No model calls, budget
  changes, new resources or authentication changes were made for this work.
- Live API now returns ten chart tiles and six grids, all with nonempty data and
  no errors. Every deployed static asset matches the tested local build exactly.
  Live API health and all existing budgets remain available. Anonymous portal
  access is still denied, and all 12 expected Azure RBAC assignments are verified.

## Acceptance

- Admin users see real charts (not just data grids) for gateway blocking, model
  tokens/cache, and Function accounting.
- Native APIM/provider 429s are distinguishable from monthly-budget denials.
- Accounting charts distinguish admission, actual finalized usage and unknown usage;
  Table/Redis operations are not mistaken for requests or multiple financial charges.
- No invented blocked token totals, no double-counted cache tokens or hierarchy spend,
  no use of sampled logs as an exact financial reconciliation guarantee.
