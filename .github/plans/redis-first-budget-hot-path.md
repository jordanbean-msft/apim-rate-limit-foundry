---
title: Redis-first budget hot path
description: Replace ledger-first admission with fast Redis checks and best-effort Table persistence.
---

## Contract and acceptance criteria

Redis is the live operational state for cached configuration, request context,
24-hour replay protection and monthly model/wildcard user/team/department spend.
Warm admission and usage recording must not read or await Table Storage.
Configuration cache misses may load durable configuration; admin configuration
CRUD remains durable-first and invalidates the shared configuration cache.
Redis loss may reset current spend and lose in-flight context. Redis unavailability
returns an explicit failure rather than a silent Table fallback.

Usage updates the applicable Redis counters atomically and idempotently within
the replay window. Request context and usage are mirrored to Table Storage by a
bounded, process-local async writer. Queue saturation, write failures and abandoned
shutdown work are logged; tasks can be lost on host termination. There is no
durable queue, global ledger lock, per-request ledger rebuild or exactly-once
durability promise. History/chargeback read the eventually persisted ledger.
Existing identity, hierarchy, pricing, unknown-usage and streaming protections stay.

## Implementation checklist

- [x] Implementing the Redis operational store and memory equivalent.
  Owner: main agent. Files: stores contracts, Redis, memory and Lua scripts.
  Add configuration cache, direct request/usage keys and atomic incremental spend.
  Remove distributed ledger locking and replacement-projection logic.
- [x] Replacing the admission/accounting flow and lifecycle.
  Owner: main agent. Files: engine, bounded background writer, runtime, API,
  configuration, streaming relay and focused tests.
  Warm checks use Redis only; accounting returns before Table writes finish.
  Remove obsolete rebuild endpoint and recovery-only code.
- [x] Updating APIM contracts and infrastructure descriptions.
  Owner: main agent. Files: APIM policies/tests, directly related Terraform
  route/description/dashboard wording and tests if applicable.
  APIM waits for Redis acceptance, not Table durability. Keep managed identities
  and best-effort export; distinguish accepted accounting from durable history.
  Cache TTLs are explicit deployed settings; Always On is enabled for both
  Function hosts in the project deployment specification.
- [x] Updating documentation and editable architecture diagrams.
  Owner: documentation agent in a separate worktree after contract approval.
  Files: README, ARCHITECTURE, documentation, APIM/infra/web READMEs and draw.io
  files only. Preserve local embedded icons and diagram editability.
  Explain cold cache, approximate budgets, eventual reports and accepted data loss.
- [x] Validating and integrating the implementation.
  Owner: main agent. Run focused `uv run pytest -W error`, policy tests,
  `uv run ruff check .`, `uv run mypy src/`, then the full warning-free Python
  suite. Prove a blocked Table writer cannot delay warm checks or usage responses,
  cover duplicate usage, concurrent hierarchy/model counters, background failures,
  cache misses/invalidation and Redis failure/reset behavior.
  Run Terraform format/validation/tests if Terraform changes.
  Validate draw.io XML, embedded icons and rendering after documentation integration.
  Complete: 132 strict Python tests passed (one optional Azurite test skipped),
  including actual Redis Lua concurrency/idempotency and end-to-end blocked-Table
  probes. All 21 gateway tests, 17 mocked Terraform tests, 116 portal tests,
  production build, lint, source types, Terraform format/validation and whitespace
  checks passed. Integrated the documentation worktree's 18 deliverable files.
  Validated 36 diagram connectors and 60 byte-identical embedded local SVG icons,
  rendered and visually checked all four pages. No deployment was performed
  during that implementation phase.

## Live deployment and behavior verification

Requested on 2026-11-15. Reuse the established publicdemo environment and existing
services. Deployment workflow proof is recorded in `.azure/plan.md`.

- [x] Validating fresh authenticated azd preview and all three service packages.
  Inspect resource actions before provisioning; preserve existing data and IAM.
  Preview: 28 in-place updates, only the retired APIM operation deleted, no
  creates or data replacements. All packages passed under Node 24.22.3 and
  contain the new Python modules and required production portal dependencies.
- [x] Provisioning the reviewed changes and deploying API, stream and web.
  Verify actual host settings and unchanged authentication after deployment.
  Completed: provisioning and all three deployments succeeded. Both Function
  hosts have Always On, 60/86400-second cache TTLs and local bypass disabled.
  Unauthenticated Functions return 401; the portal redirects to sign-in.
- [x] Proving bounded live allow/deny and ordinary/SSE accounting behavior.
  Inspect Redis operational keys/counters and eventually persisted Table records;
  never flush or delete shared data. Limit inference to 60 calls and the user's
  explicitly approved $10 ceiling, restoring temporary test configuration.
  Completed: 12 attempts, seven successful and five denied, costing $0.000308.
  Chat/Responses ordinary/SSE, hierarchy/model/zero caps, cross-model isolation,
  soft-cap crossing and replay passed. Nine Redis counter deltas matched priced
  usage; Table contained all 12 contexts and seven matching usage events.
  Denials were uncharged. Original active configuration was restored exactly.
- [x] Verifying actual dashboard queries and correlated telemetry against the
  probe request IDs. Record ingestion delays and any genuine limitations.
  Completed: all 16 deployed queries passed; exact IDs showed 12 decisions,
  seven usage events, five denials and 21 successful background operations.
  Four warm checks took 20.596-24.499 ms with no Table reads; Table admission
  mirrors finished 12.026-18.654 ms after responses. Direct Event Hub metrics
  showed seven incoming messages and no throttling/server/user errors.
  One Log Analytics refresh timed out; its explicit retry passed. The Event Hub
  workspace tile had no metric rows, and integrated browser access timed out.
  Actual authenticated dashboard API and telemetry were verified, not UI rendering
  or production load capacity. Sanitized reports and full proof are referenced
  in `.azure/plan.md`. The owned SSH tunnel was closed.
