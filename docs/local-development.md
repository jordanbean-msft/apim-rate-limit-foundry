# Local development

Use Python 3.12+, `uv`, Node.js 24 LTS and Terraform 1.9+. Do not use global pip
or install package versions outside the repository manifests.

```bash
uv sync --extra dev
cp .env.example .env
uv run apim-rate-limit-foundry
```

Local mode must explicitly enable authentication/storage bypasses. On loopback,
send `X-Local-Tenant-Id`, `X-Local-Principal-Id` and `X-Local-Roles` for test actors.
These are not supported deployment credentials and are prohibited in Azure.

```bash
uv run python scripts/seed.py
uv run python scripts/seed.py --apply
```

The first invocation previews illustrative records. The second explicitly writes
organizations, assignments, prices and budgets. Configure a model registry that
matches those aliases before inference; sample endpoints are not callable models.

For persistent local stores, `docker compose up -d` starts Redis/Azurite on
loopback. Set both local endpoint settings in `.env`, create the configured Table,
and rebuild the monthly projection. Do not use shared production Redis databases.

The API and streaming Functions have separate entry points/hosting modes:
`function_app.py` and `stream/function_app.py`. VS Code's `run-api`,
`run-functions`, `run-stream`, and corresponding debug configurations preserve
that separation.

## Validation

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -W error
uv run python -W error -m unittest discover -s apim/tests -v
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
terraform -chdir=infra test
```

Terraform validation must have zero warnings as well as zero errors. Optional
real Redis/Table integration tests require their documented test environment
variables. No unit test should need paid inference or cloud credentials.

See `.vscode/tasks.json` for grouped validation and `.vscode/launch.json` for
debuggers. Deployment and live acceptance are separate from local fixture tests.
