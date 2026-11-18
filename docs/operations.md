---
title: Operations
description: Diagnose gateway requests, understand data-loss limits and verify deployed behavior.
---

## Overview

Use [deployment](deployment.md) to prepare the environment and
[observability](observability.md) to find logs and dashboard queries.
The [architecture](../ARCHITECTURE.md#key-design-decisions) explains the choices
behind these operating limits.

## Request diagnosis

Start with `X-Correlation-ID`, then join APIM requests and Function events.
Budget denials return limiting budget IDs and UTC reset/retry information.
Distinguish native gateway/provider throttles from monthly dollar-budget denials.
Changing an application key must not reset a user's budget.

## Redis availability and accepted loss

Redis is the live operational budget state, not a projection rebuilt from Table.
Warm admission never reads Table. Shared configuration snapshots expire after
60 seconds by default; only a cold miss loads durable assignments, organizations,
prices and budgets. Admin CRUD remains synchronous durable-first with cache
invalidation. Request context and usage replay markers last 24 hours; monthly
user/team/department wildcard/model counters last about 62 days.

Redis unavailable means fail-closed `503`, without Table fallback. An exhausted
budget, including a zero limit, means `429`. Redis **data loss** is different from
unavailability: after service returns, missing counters can reset spend and
missing context can prevent accounting an admitted request. There is no automatic
ledger rebuild, global ledger lock or per-request full ledger read. Do not delete
keys as a recovery step unless a reset of approximate budgets is explicitly
accepted. Persisted history does not restore the lost live allowance state.

Entra token refresh builds the new Redis client first and swaps it in while
commands keep using the still-valid one; the replaced client is closed at the next
refresh or at shutdown, never while commands may still be using it.

Each runtime shares one serial, process-local `asyncio` worker for request/usage
Table mirrors and Event Hub exports: 256 pending jobs, plus the active job.
Slow Table operations or Event Hub SDK retries delay subsequent jobs and can
cause either destination's work to be dropped. Any exception escaping a job is
logged (`background_write_failed`), then the worker continues. APIM never waits
for these jobs. Monitor `background_write_dropped`, `background_write_failed`
and `background_writes_abandoned`; graceful close attempts a best-effort
two-second drain. Restarts, failures and saturation can permanently lose history
or exports. Usage replay returns the accepted record and does not repair
dropped mirrors or exports.
There is no durable queue, application retry worker, outbox or exactly-once
persistence guarantee. The Azure Event Hubs SDK retains its default transport
retry policy; that does not make the worker durable.
Table outages do not block a warm check or Redis-accepted usage, but can block
cold configuration loads and durable-first admin CRUD.

Recorded usage contributes dollars without reservations. Concurrent requests can
overshoot. Unknown usage (aborted streams, failed provider opens, missing or
invalid provider counters) is charged a conservative upper bound from the pinned
price and model ceilings, marked `cost_basis=estimated_upper_bound`, and still
warrants operator review: see [token accounting](token-accounting.md). Real usage
above the pinned ceilings is priced as reported and flagged
`out_of_bounds`/`usage_out_of_bounds`. Retained history/chargeback may lag or
permanently differ from live Redis spend. Investigation cannot promise financial
completeness or recover data that was never persisted.

## Durable history keys

Request, usage and configuration rows share one Table. Configuration and audit
rows stay in the `ledger` partition so they can change in one transaction.
Usage history is written to a partition per tenant and UTC month
(`usage:<tenant>:<YYYY-MM>`), so `GET /usage` and `GET /chargeback` query a single
partition instead of scanning and filtering every row. `GET /usage` accepts an
optional `month=YYYY-MM` (default: the current UTC month). Usage mirrored before
the tenant/month partition format is **not migrated or read**. Reports only
include records in the configured tenant/month usage partition; an empty report
does not prove there is no data elsewhere in the Table.

Invalid stored configuration is not silently dropped: a record without its
collection's current-schema marker field (`kind`, `principal_id`, `subject_type`
or `input_per_million`) is archived legacy data and skipped, but a current-schema
record that fails validation is logged (`configuration_record_invalid`) and makes
admission and configuration reads fail closed (`400`) until an admin replaces or
deletes it, because dropping a budget would remove its cap.

Before changing deployed schemas or replacing stores, preserve access-controlled
backups of configuration, usage, audit data and remote Terraform state. Do not
relabel incompatible records or clear shared Redis databases. An operational
spend reset requires explicit approval; retained Table history cannot rebuild it.
The [archive utility](../scripts/archive_legacy_config.py) can wrap a JSON export
in an exclusive-write archive with schema metadata and a SHA-256 digest:

```bash
uv run python scripts/archive_legacy_config.py --input export.json --output archive.json
```

The utility does not connect to Azure or infer organizational ownership. Protect
exports as sensitive data; they can contain tenant and principal identifiers.

## Event Hub export gaps

The budget and streaming Functions publish with their managed identity. Check
Sender RBAC on the hub, `EVENT_HUB_FQDN`/`EVENT_HUB_NAME`, private DNS/egress,
`usage_event_publish_failed` logs and Event Hub incoming/throttled/error metrics.
No application retry worker or replay repair exists; SDK transport retries may
occur within the queued send.

Publication is best effort. An accepted send or incoming-message count is
not end-to-end downstream processing confirmation. Compare stable event IDs
against retained Table history and other evidence; an event indicates Redis
acceptance, not Table persistence, so either side can have gaps. Downstream
consumers own checkpoints/deduplication.

For `collection=usage_event`, `background_write_completed` only means the
publisher returned, including after a handled send failure. Check
`usage_event_publish_accepted` or `usage_event_publish_failed` for the broker
delivery outcome. Likewise, `runtime_closed` means clients closed after an
attempted bounded drain, not that every job persisted.

## Acceptance checklist

- Require valid Entra user and product key; reject missing/forged identities.
- Use the same user through two application subscriptions and confirm pooled user spend.
- Independently exhaust user, team, department and model-specific monthly budgets.
- Verify no provider call on denial and document concurrent in-flight overshoot.
- Exercise Chat and Responses, both JSON and SSE, including cached input.
- Compare provider terminal totals, Redis spend, eventual usage, Event Hub event and
  chargeback export; allow persistence lag and explicitly record unrecoverable gaps.
- Interrupt a stream before the provider reports terminal usage (for example by
  failing the provider open) and verify the unknown usage is visible and charged the
  documented upper bound, rather than zero. A client disconnect is priced from
  terminal usage only if that usage was already observed; otherwise finalization
  attempts the unknown-usage estimate. Finalization cannot reconstruct unseen
  provider totals.
- Stream a Responses generation larger than `STREAM_MAX_EVENT_BYTES` and verify it
  is priced from its terminal usage.
- Simulate recording/export dependency failures without inventing success.
- Block Table writes and verify warm checks/usage responses do not wait; exercise
  background saturation/failure logging and best-effort shutdown.
- Verify usage replay does not double debit within 24 hours, cold configuration
  misses load Table, and durable admin updates invalidate the shared snapshot.
- Verify Redis unavailability returns `503` without Table fallback and document
  that Redis data loss can reset spend/lose admitted context without a rebuild.
- Execute every persisted Azure dashboard query for fresh test traffic. A Log
  Analytics query timeout (`DASHBOARD_QUERY_TIMEOUT_SECONDS`, default 20) marks
  the affected tiles "timed out" and logs `dashboard_query_failed`
  (`status=timeout`); an overall deadline returns `504` and `dashboard_timeout`.

Local tests do not establish live APIM policy compilation, Government availability,
interactive sign-in, private-network connectivity or financial completeness.
