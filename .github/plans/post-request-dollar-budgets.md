# Post-request dollar budgets

Source: approved session plan, `34977282-45ef-426e-ab3b-d62e79acff16/plan.md`.
The code cutover preserves historical usage without relabeling. The subsequent
Azure resource retirement was explicitly approved by the user.

- [x] Backend owner: replace reservations with monthly user/team/department checks,
  finalized OpenAI usage and chargeback; validate warning-free Python tests and types.
  Status: integrated `e1c882d`; final Python validation passes: 76 tests, one optional
  live-storage test skipped, 80.67% coverage, lint/format and mypy. Both package builds pass.
  Integration regressions cover distinct APIM/user identities, incomplete Responses,
  disconnects after terminal usage, month rollover and zero budgets at every level.
- [x] Gateway/infrastructure owner (isolated worktree): OpenAI-only APIM policies,
  native Event Hub logger, streaming callback, Terraform and Azure dashboard/KQL.
  Validate policy tests and zero-warning Terraform formatting/validation/tests.
  Status: integrated `c630ccd`; parent reran 20 APIM tests and 17 Terraform plans.
  Formatting and Terraform validation pass with zero warnings/errors. The approved
  Azure cutover subsequently completed; live dashboard and route checks pass.
- [x] Portal owner (isolated worktree): organization assignments, monthly dollar
  budgets, actual spend, chargeback and shared Azure dashboard; validate frontend suite.
  Status: integrated `621d0f0`; pre-existing telemetry/main edits preserved. Parent
  verified lint, types, 91 tests and production build with Node 24, including null-valued
  unknown chargeback counts.
- [x] Parent: replace operational docs, diagrams, examples, seed/migration tooling and
  VS Code tasks; preserve unrelated pre-existing changes.
  Status: consolidated docs and Mermaid diagrams, explicit seed records and exclusive-write
  archive tool implemented. Nine tooling tests, JSON/link checks and lint/format pass.
- [x] Parent: integrate isolated patches and run combined Python, APIM, frontend and
  Terraform validation; report live acceptance limits without inventing evidence.
  Status: all offline checks pass: Python strict coverage, frontend lint/types/tests/build,
  20 APIM policy tests, 17 Terraform tests and zero-warning Terraform validation.
  Example seed records pass the actual API, both protocols and three-level reporting;
  chargeback totals reconcile to the ledger. Local links, JSON and whitespace checks pass.
  Offline verification preceded the separately approved Azure deployment below.

- [x] Deployment follow-up: validate and provision the approved `publicdemo` cutover,
  deploy API/stream/web, verify live endpoints and dashboard, and open the app.
  Status: provisioning and all three deployments succeeded. APIM fragment removal
  required a reference-safe policy switch; no temporary retention blocks remain.
  Authenticated API/APIM checks pass; missing token/key returns 401; production
  workload identities, Event Hub Sender/callback roles and portal Key Vault
  resolution are verified. Redis rebuild passes and all nine dashboard queries pass
  after a tested KQL numeric-type fix. Browser opener succeeded.
  New organizations, assignments, prices and budgets are intentionally empty.
  At initial cutover, paid inference, live streaming, Event Hub ingress and
  interactive sign-in/MFA were untested; subsequent live checks are recorded below.
  No historical usage was reclassified.

Dependencies: shared API contracts precede each implementation. Integration follows all
three workstreams. Historical application-scoped data must be archived, never reclassified.
Monthly limits are soft: requests already in flight can overshoot.
The sample reads authoritative finalized records and rebuilds the disposable Redis
projection during checks; throughput and ledger-growth validation remain deployment
considerations, not a claim of a production-optimized counter hot path.

- [x] Live demo follow-up: populate current Azure Global Standard prices and demo
  hierarchy/subscriptions, generate real successful and dollar-limited requests,
  and reconcile streaming usage, chargeback and native Event Hub ingress.
  Status: three current Azure price cards, five organization units, four profiles,
  twelve budgets and three subscriptions seeded. Real traffic uses the delegated
  reviewer, not fake identities. All models and both protocols pass JSON/SSE usage
  reconciliation. Eighteen actual records total $0.001581, 324 input and 160 output
  tokens; nine 429s cover all hierarchy levels. Chargeback reconciles across two
  business units. The pre-fix Responses unknown record remains immutable and unpriced.
  A zero cache-write compatibility fix passed lint/types and 38 strict regression
  tests, then deployed to both Function hosts. Dashboard denial correlation/list
  parsing and health metric typing fixes passed live behavioral queries, two
  Terraform tests and zero-warning validation before non-destructive provisioning.
  All nine tiles are populated, denial counts are 3/3/3 and Event Hub metrics show
  19 incoming messages with zero errors/throttles. Nano is intentionally limited;
  mini/full remain available. No downstream-consumer or interactive MFA claim.
