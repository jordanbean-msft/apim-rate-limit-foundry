# Illustrate documentation and review the deployed dashboard

## Scope and acceptance

Improve the existing canonical guides instead of duplicating them. Add real browser
captures with explicit live/demo provenance, readable diagrams, and executable
examples without secrets. Review the deployed Commercial dashboard's persisted
queries, axes and results against the documented cost/model, cache economics, caller
attribution and shared-service requirements. Do not imply Government certification
or claim signed-in Azure portal rendering from ARM/query inspection alone.

## Work

- [x] Inspect browser/auth tooling and live dashboard resources and queries.
  Owner: main agent. Read-only Azure access; preserve unrelated worktree changes.
- [x] Capture sanitized screenshots and add a visual request/configuration tour.
  Owner: main agent. Depends on inspection. No production auth bypass or test JWTs.
  Five live app captures; identities masked, zero writes/errors. Separate Azure
  portal requires interactive sign-in, so only ARM/KQL review is claimed there.
- [x] Add targeted README/guide diagrams and runnable code/configuration examples.
  Owner: main agent. Depends on verified UI and actual route/schema contracts.
  Five live screenshots, two query-result SVGs, concise README map, full Azure
  resource inventory/map, pricing diagram, HTTP/PUT and in-process Python examples.
- [x] Record dashboard relevance, live evidence and any limitations in observability.
  Owner: main agent. Depends on persisted query inspection and live query execution.
  Fix directly related chart defects if found, with Terraform checks before any
  separately validated/deployed infrastructure change.
  All 22 deployed queries execute; decision/cost/token/429/stream-release checks
  pass. Explicitly document two legacy unknown-cost admissions and incomplete
  caller attribution. No infrastructure changes identified as necessary.
- [x] Validate changed links/examples, render diagrams, inspect screenshots, and run
  scoped hooks/diff checks. If dashboard source changes, run its tests, Terraform
  formatting and warning-free validation. Mark complete only after evidence exists.
  253 links/anchors across 14 guides, 22 shell templates, two executable Python
  examples and the PUT policy JSON validate. All 15 diagrams render; five live
  screenshots and two chart graphics inspected; hooks/diff checks pass. Both
  documented mocked dashboard tests pass (Commercial/Government wiring only).
  Final consistency review distinguishes 31 missing original-hold observations
  from two unknown effective liabilities; missing data is never called free.

## Result

Documentation and assets only: no runtime or infrastructure source changes, no
Azure configuration changes, no inference calls, and no new tooling dependencies
in project manifests. All work is in the existing guides and `docs/images/`.
Full read-only review/capture evidence and helpers remain in the session workspace;
the existing ignored deployment query verifier was also executed successfully.

## Validation boundaries

Use the existing approved delegated session only in an isolated browser context.
Never retain tokens, identity-bearing screenshots, browser storage, HAR or traces
in the repository. Label fixture screenshots as fixtures and any query-result
visualization as such, not as the Azure portal. Keep full operational evidence in
the ignored deployment/session directories and publish only safe aggregate results.
