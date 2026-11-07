# Support multiple model deployments

## Contract and scope

- Keep the existing Chat, Responses and Messages routes and conservative
  reserve/settle accounting; do not change rate-window semantics.
- Identify each registered route by `<protocol>:<alias>`, for example
  `openai-chat:chat-fast`. The alias is the client `model` and accounting/pricing
  model. The provider deployment name can differ.
- Generate one allowlisted registry from Terraform for APIM and both Function
  hosts. Each runtime entry contains `api_protocol`, `endpoint`, `path`, `model`
  (provider deployment), `audience`, `api_version`, `anthropic_version`,
  `price_version`, `max_input_tokens`, and `max_output_tokens`.
- Retain legacy single-model Terraform inputs and `STREAM_BACKENDS` compatibility.
  Registry lookup is exact by protocol and alias; unknown or incompatible aliases
  fail before reservation/dispatch. Ambiguous duplicate routes fail configuration.
- Expose a read-only, role-protected `GET /api/models` list with `id` (registry
  key), `model` (alias), `api_protocol`, `deployment_name`, `price_version`,
  `max_input_tokens`, and `max_output_tokens`; never expose backend destinations
  in the portal contract.
- Support different price cards per alias and existing wildcard policies for a
  caller's combined model budget. Prices remain pinned for in-flight requests.
- No live Azure provisioning, new dependencies, unrelated review fixes, or
  provider upgrades are required.

## Checklist and ownership

- [x] Define the cross-layer registry contract and inspect applicable instructions.
- [x] Implement runtime registry validation, model-scoped admission, protected
  discovery and exact streaming dispatch (parent: `src/`, `tests/`, `.env.example`).
  Acceptance: two models of each protocol, alias/provider distinction, wrong
  protocol/unknown alias rejection, distinct prices, pooled budgets and legacy
  behavior. Validate Python tests with `-W error`, Ruff and mypy.
  Complete: 175 Python tests passed (8 external-store skips); Ruff and mypy
  passed. Catalog/registry edits preserve replay and in-flight price snapshots.
- [x] Implement additive Terraform registry, generated APIM model selection,
  per-model bounds/routing/prices, RBAC/diagnostic deduplication and portal route
  (infrastructure agent: `infra/`, `apim/`, their tests).
  Depends on the contract above, not on Python implementation. Acceptance:
  multiple models per protocol, no per-model policy branches, legacy migration
  safety, Commercial/Government gates, and no caller-selected backend.
  Complete: 24 mocked Terraform runs and 32 warning-free gateway tests passed;
  formatting and validation reported zero errors and zero warnings.
- [x] Implement portal model inventory and model-aware policy/price workflows;
  update examples and current documentation/architecture (portal/docs agent:
  `web/`, `README.md`, `ARCHITECTURE.md`, `docs/`, `examples/`).
  Depends on the discovery contract above. Acceptance: multiple same-protocol
  models and distinct prices are visible, deployed routing is read-only, and
  adding a model is explained without overstating cloud availability.
  Complete: integrated portal lint/types/format, 82 tests and build passed.
  All six documented registry entries admit with the sample prices and pooled
  budget; distinct fast/standard prices were verified through the Engine.
- [x] Integrate isolated worktree patches without reverting existing changes;
  review cross-layer configuration, instructions, VS Code tasks and diagrams.
  Complete: integrated both patches and preserved overlapping existing test
  changes. Restored non-LLM model/price defaults, exposed all aliases in route
  outputs, retained legacy diagnostic addresses and supported dated preview
  API pins. Existing VS Code tasks/launch configurations cover unchanged commands.
- [x] Run combined warning-free Python/gateway tests, lint/types, portal checks,
  Terraform fmt/validate/mocked tests; verify final plan and migration docs.
  Complete: 175 Python tests (8 external-store skips), 32 gateway tests, 82
  frontend tests and 24 Terraform runs passed. Ruff, formatting, mypy, frontend
  lint/types/build and Terraform checks passed. Exact generated registries were
  compared between APIM and both Functions for six Commercial and four Government
  entries, including deduplicated identity grants; 21 emitted Function settings
  passed the real runtime schema. Loopback API startup/auth/read-only discovery
  and all six documented example prices were verified. Live Azure provisioning
  and unavailable real Redis/Azurite tests were not performed.

## Parallel-work safeguards

Agents use separate new worktrees/branches populated with the current working
tree snapshot. Each edits only its ownership boundary and returns a patch
relative to that snapshot; no agent commits or modifies the main working tree.
This plan is the durable source of progress. Agents update only their assigned
checkbox and record blockers beside it; the parent integrates the final state.
