# Chart-first rate-limiter dashboard

Add graphical views to the existing shared Azure dashboard while retaining its
investigation tables, replay-safe accounting and Commercial/Government links.
Do not resize hosting, redeploy applications or change live rate-limit settings.

- [x] Add six chart queries for decision mix, throttling over time, effective USD
  over time, blocking policy/metric, actual token/cache composition and limiter
  latency. Keep the existing admission chart and seven detail tables. Own
  `infra/modules/monitoring/` and focused dashboard Terraform tests.
- [x] Bind each chart's actual category/time/value/series columns, use supported
  Azure Monitor visualizations, and update operator documentation. Keep mixed
  units separate and distinguish final cost from conservative liability.
- [x] Validate Terraform format/schema/tests/hooks and execute all queries against
  the live workspace. Validate chart metadata against returned result schemas.
  Preview monitoring-only provisioning; require no workload updates/deletions.
  Recursive format/validate, both cloud dashboard plans, TFLint/hooks pass.
  All 14 live queries pass with seven populated chart datasets; axis schemas and
  decision/denial/cost/token totals verified. Actual scoped preview proves only
  one in-place dashboard update, no additions/deletions or workload changes.
- [x] Deploy through the validated azd workflow with monitoring-only scope, then
  verify the persisted chart types/dimensions, inherited tags, time behavior and
  populated live queries. Preserve existing hosting drift and user documentation.
  Provisioned: zero additions, one dashboard update, zero deletions. Persisted
  ARM resource has seven chart and seven grid controls; all query text, chart
  types, time inputs, workspace scope, dimensions and numeric types verified.
  All 14 persisted queries execute; seven chart datasets contain representative
  telemetry and decision/denial/cost/token totals reconcile with the detail tables.
  Existing Owner/workspace query access confirmed, with no role changes.
  Azure portal browser rendering remains unverified because interactive sign-in
  is required; metadata and actual query results were verified, not screenshots.
  Evidence is ignored under `.azure/publicdemo/dashboard-charts-persisted.json`
  and `dashboard-charts-provision.log`.

Dependencies: chart queries and metadata precede validation; validation precedes
provisioning. Acceptance: seven visible chart definitions plus seven detail tables;
deduplicated decisions/settlements, all-or-none denial semantics, no double-counted
reservation/settlement cost and no claim that missing traces prove native throttling.
