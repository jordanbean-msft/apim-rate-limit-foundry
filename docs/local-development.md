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
and seed configuration. The first cold check loads the shared configuration
snapshot; warm checks use Redis only. Do not use shared production Redis databases.
Clearing local Redis resets approximate spend and can lose admitted context;
there is no automatic rebuild from Table history.

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

Terraform validation must have zero warnings as well as zero errors. No unit
test should need paid inference or cloud credentials.

To exercise actual Redis Lua concurrency/idempotency behavior, start an isolated,
disposable Redis instance bound to loopback only, then run:

```bash
TEST_REDIS_URL=redis://127.0.0.1:<port>/0 uv run pytest -W error tests/test_redis.py
```

Replace `<port>` with that instance's local port. Never point these tests at
shared, persistent or deployed Redis: they may change/delete test state.
Stop and discard the isolated instance after testing. Optional Table integration
tests require their separately documented local test settings.

See `.vscode/tasks.json` for grouped validation and `.vscode/launch.json` for
debuggers. Deployment and live acceptance are separate from local fixture tests.
