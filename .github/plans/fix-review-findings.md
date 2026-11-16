# Fix repository review findings

Source of truth for progress. Mark items `- [x]` only after implementation and validation finish.

## Workstreams (each in its own worktree/branch)

### A. accounting — branch `fix/accounting` (owns `accounting.py`, `models/`, `streaming/`, `stream/function_app.py`, price examples)

- [x] Add optional cache-write price and `cache_write_tokens` to normalized usage (typed `UsageCounts` model, not a dict).
- [x] Price usage above pinned model bounds with real counts and flag it, instead of recording `usage_unknown` with no cost.
- [x] Stop Responses streams larger than the event bound from becoming $0 (parse terminal usage without retaining `output`).
- [x] Charge a conservative documented fallback for unknown/aborted usage (client disconnect mid-stream) so budgets still decrement.
- [x] Inject the aiohttp session into the stream relay; remove the `global runtime` mutation in `stream/function_app.py`.
- [x] Update `docs/token-accounting.md`; tests for every new path.

### B. reliability and structure — branch `fix/reliability` (owns `background_writer.py`, `stores/`, `runtime.py`, `api.py`, `telemetry.py`, engine edits outside `_record_usage`)

- [x] `BackgroundWriter` survives any per-job exception and logs it.
- [x] Redis token refresh swaps in the new client before closing the old one; no global serialization of commands.
- [x] `Engine.configuration` skips only legacy records; invalid current-schema budgets are logged (fail closed).
- [x] Usage/chargeback queries filter in Table Storage (tenant + month keys) instead of scanning the whole collection.
- [x] `api.py` uses `CONFIG_MODELS` allowlist; no private `get_engine()._assignment` calls; remove dead `telemetry.observe_operation`.
- [x] Dashboard query timeout is configurable and handled.
- [x] Tests for every new path.

### C. backend pools — branch `fix/backend-pools` (owns `infra/`, `apim/`, `docs/azure-topology.md`, `docs/model-registry.md`, `docs/diagrams/*.drawio`)

- [x] Native APIM backend pools (priority/weight) with circuit breakers for model aliases that list additional endpoints.
- [x] Policy routes to the pool backend ID; managed identity auth retained.
- [x] Terraform tests and APIM policy tests; `fmt`, `validate` clean.
- [x] Docs and diagrams updated.

### D. docs and housekeeping — branch `fix/docs` (owns README, `docs/diagrams/README.md`, `examples/`, `.github/plans/`)

- [x] README quick start, verify and cleanup sections; simplified-diagram note linking the physical diagram.
- [x] Remove personal local path from `docs/diagrams/README.md`; fix stale source links.
- [x] `examples/gateway.http` uses a registered model.
- [x] Remove stale `normalization/` directory; mark `support-three-llm-protocols.md` superseded.

### E. phase 2 (after merge) — branch `fix/engine-split`

- [x] Split `engine.py` into single-responsibility services (`src/apim_rate_limit_foundry/engine/`); shorten long functions.
- [x] Close the Python coverage gaps listed in the review (total 99.9%, `fail_under = 95`, includes both `function_app.py` entry points).
- [x] Final validation: `uv run ruff check .`, `uv run mypy src/`, `uv run pytest -W error --cov`, web checks, Terraform fmt/validate/test.
