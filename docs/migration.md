---
title: Cutover from application-scoped accounting
description: Migrate accounting contracts without relabeling historical financial data.
---

## Cutover

The new ledger is not compatible with monetary holds or application budgets.
**Do not relabel old records as user/team/department spend.**

1. Stop or drain inference traffic before changing the deployed accounting API.
2. Export the old configuration/usage/audit collections and preserve an access-
   controlled backup of the Table data and remote Terraform state.
3. Use a **new empty Table name** for the dollar-budget deployment and a separate
   Redis namespace or reviewed clean instance. Keep the old table read-only.
   Never clear shared Redis databases or destroy historical records.
4. Configure the new explicit organizations, user assignments, monthly budgets
   and approved model price versions. Preview seed records before applying them.
5. Review the Terraform plan, especially removal of previous AI-service routes/
   resources. Do not apply a replacement/deletion merely because local tests pass.
6. Deploy API, stream relay, APIM and portal as one reviewed contract cutover.
7. Verify cold configuration loading and shared-cache invalidation, run the
   acceptance checks, then restore traffic. New Redis counters start empty;
   history is not automatically replayed to reconstruct spend.

For an existing dollar-budget deployment moving from ledger-authoritative checks,
choose a reviewed cutover boundary and explicitly accept any reset of current
operational spend. The Redis-first contract has no automatic ledger rebuild or
per-request full ledger reads. Warm checks use Redis only; Redis unavailability
returns `503` without Table fallback. Data loss can reset spend or lose admitted
context. Request/usage Table mirrors are now best effort through a bounded
process-local writer, not awaited by APIM, and can be lost permanently. Persisted
reports are no longer guaranteed to match live budgets. Preserve retained history
and document the discontinuity rather than promising a lossless migration.

APIM rejects deletion of fragments or backends still referenced by live policies.
For an existing deployment, stage the policy transition before retiring those
objects: temporarily retain the existing reservation fragments without changing
their values, apply the new operation policies, then remove the retained
fragments and apply again. Remove obsolete APIs before their backends and allow
Azure's reference cleanup to finish. Do not retain reservation behavior in the
final configuration or bypass APIM validation with state removal.

For JSON backups, `uv run python scripts/archive_legacy_config.py --input export.json
--output archive.json` creates an exclusive-write archive with schema metadata and
a SHA-256 digest. It does not connect to Azure or infer organizational ownership.
Store the archive securely: it can contain tenant and principal identifiers.

Usage history is keyed by Table partition `usage:<tenant>:<YYYY-MM>` so reports
query one month directly. Records written under the earlier single `ledger`
partition are not read or migrated by this sample.

Configure real records through the administration API or portal. Optional
fictional records have a separate [demo loader](../demo/README.md), which
requires empty, isolated stores and never migrates old financial history.

Historical `.github/plans/` files remain historical evidence only. They are not
instructions to restore the removed system.
