---
title: Deploy and refresh sample data
description: Track the deployment, separate seed workflow, and end-to-end verification.
---

## Ownership and dependencies

One agent owns this sequential workflow. Deployment approval and validation
precede provisioning; explicit reset approval and stopped writers precede cleanup
and seeding. Deployment-specific details and validation proof live in the
ignored [deployment plan](../../.azure/deployment-plan.md).

## Checklist

- [x] Inventory existing azd resources, data stores, and model routes
- [x] Confirm region, reset scope, downtime, and USD 5 live inference test cap
- [x] Validate infrastructure and application artifacts
- [x] Provision existing infrastructure and deploy API, stream, and portal
- [x] Back up and clear approved disposable application data with writers stopped
- [x] Load separate Office dataset and verify persisted accounting projections
- [x] Generate bounded live gateway tests within the approved spend cap
- [x] Verify success, denials, replay, history, chargeback, and budget visibility

## Verified outcome

All three services are deployed and running. Old application data was backed up
and reset with writers stopped. Office seed plus generated activity produced
86 synthetic events; 10 real inference calls added verified costs at configured
rates. All 44 spend fields reconcile with 96 durable events. Monthly and native
burst 429s, noncharging replay, cached pricing, reports, and all 16 dashboard
queries pass. Temporary deployer Redis access was revoked.

The integrated browser requires interactive Entra sign-in; authenticated visual
inspection is not claimed. The mapped user's nano model budget deliberately
remains exhausted for testing and can be raised in the portal.

## Acceptance criteria

Application artifacts exclude demo data and tooling. Cleanup affects only
explicitly approved stores. Seeded and live usage have verified Table history
and Redis totals. Report actual live test costs separately from synthetic data
and identify any unverified behavior.

## Validation

- `terraform -chdir=infra fmt -check -recursive`
- `terraform -chdir=infra validate`
- `uv run pytest -W error demo/tests`
- `uv run ruff check .`
- `uv run mypy src/ demo/seed.py`
- Existing application packaging and web build commands
- Live endpoint, data-plane access, and accounting assertions
