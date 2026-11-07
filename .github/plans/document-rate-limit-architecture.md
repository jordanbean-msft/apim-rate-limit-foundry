# Explain the rate-limiting architecture

Document the implemented system with repository-rendered Mermaid diagrams and a
worked operator walkthrough. Documentation only; no service, policy or runtime changes.

- [x] Update `ARCHITECTURE.md` with component, admission, lifecycle, asynchronous
  document, configuration, recovery and telemetry diagrams. Explain actual policy
  scoping, ordering, persistence boundaries and failure behavior against source.
- [x] Add `docs/rate-limiting-walkthrough.md` with a concrete multi-rule/cache-pricing
  example, GUI workflow and dashboard/log investigation. Link it from the README
  and existing configuration/operations documentation. Depends on architecture.
- [x] Validate Mermaid syntax/rendering, local documentation links, pricing example
  against the accounting implementation and changed-file hooks. Review the final
  diff for unsupported claims and record limitations. Depends on both writing items.

Acceptance: readers can distinguish APIM safety rails from Function decisions,
Redis atomic state from durable accounting, actual from conservative settlement,
and shared policy definitions from per-principal counters. Diagrams must not imply
an SSE proxy, guaranteed streaming reconciliation, distributed ACID, cross-cloud
fallback, or a fleet-wide aggregate tenant budget.

Validation completed: all seven Mermaid diagrams rendered locally with Mermaid CLI;
44 local documentation/source links and heading anchors resolved; the worked
8,000/1,850 micro-USD reservation/settlement and 1,350 micro-USD cache savings match
the actual accounting implementation. Changed-file pre-commit hooks and
`git diff --check` pass. Documentation was checked against the engine, accounting,
Lua/Table stores, gateway policies, portal API/telemetry and monitoring module.
No application, infrastructure, dependencies or deployed settings were changed.
