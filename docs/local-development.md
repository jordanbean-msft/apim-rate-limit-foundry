# Local Development

<!-- TODO: Update with project-specific setup details. -->

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Terraform >= 1.9](https://developer.hashicorp.com/terraform/install) (for infrastructure work)
- [tflint](https://github.com/terraform-linters/tflint) (for Terraform linting)

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd template-repository

# Install dependencies
uv sync --extra dev

# Copy environment file
cp .env.example .env
# Edit .env with your values

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

## Open in VS Code

Open the workspace file for the best experience:

```bash
code template-repository.code-workspace
```

## Run the API

```bash
uv run template-repository
```

The API will be available at `http://localhost:8000`. OpenAPI docs at `http://localhost:8000/docs`.

## Validation

```bash
# Lint
uv run ruff check .

# Type check
uv run mypy src/

# Tests (strict — warnings as errors)
uv run pytest -W error

# Tests with coverage
uv run pytest --cov --cov-report=xml --cov-report=term-missing

# Security scan
uv run bandit -r src/
uv run pip-audit
```

## VS Code Tasks

Use `Ctrl+Shift+P` → "Tasks: Run Task" to access pre-configured tasks:

- **sync-venv** — Install/sync dependencies
- **lint** / **lint-fix** — Run ruff
- **test** / **test-strict** — Run tests
- **coverage** — Generate coverage report
- **validate** — Lint + strict tests in sequence
- **pentest** — Run security scans
- **infra:lint** — Terraform fmt + validate + tflint
