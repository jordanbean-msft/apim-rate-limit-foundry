---
description: Python tooling conventions for this repository
applyTo: "**/*.py"
---

## Package Management — Always use `uv`

* `uv add <package>` — add a dependency
* `uv add --group dev <package>` — add a dev dependency
* `uv sync --extra dev` — install/sync environment with dev extras
* `uv sync --reinstall-package <name>` — force reinstall a specific package
* `uv run <tool>` — run a CLI tool within the managed environment
* `uv run pytest` — run tests
* `uv run ruff check .` — run linter
* Never use raw `pip install` in this project.
* **Prefer packages published and maintained by Microsoft** whenever they provide the required functionality. Add a third-party package only when no suitable Microsoft-published package exists, and document the reason in the pull request.

## Pre-release Packages

* Never use `--prerelease=allow` globally (it promotes all packages to pre-release).
* Pin specific pre-releases explicitly in `pyproject.toml`:
  ```toml
  [tool.uv]
  prerelease = "if-necessary-or-explicit"
  constraint-dependencies = [
      "some-dep>=1.0.0b5,<1.0.0b6",
  ]
  ```

## Linting and Formatting

* Lint: `uv run ruff check .`
* Auto-fix: `uv run ruff check . --fix`
* Format: `uv run ruff format .`
* Type check: `uv run mypy src/`

## Testing

* Run all tests: `uv run pytest`
* Strict mode (warnings as errors): `uv run pytest -W error`
* With coverage: `uv run pytest --cov --cov-report=xml --cov-report=term-missing`

## Pre-commit Hooks

* Install: `uv run pre-commit install && uv run pre-commit install --hook-type pre-push`
* Run manually: `uv run pre-commit run --all-files`

## LLM and AI Interactions — Always use Microsoft Agent Framework

* **Always use the Microsoft Agent Framework** (`microsoft-agents`) for interactions with LLMs instead of lower-level Azure AI Projects library.
* Always install the **latest version** of `microsoft-agents` from PyPI.
* Only use `azure-ai-projects` (lower-level SDK) when there is no Agent Framework abstraction available for your use case.
* Agent Framework provides a higher-level, more maintainable interface for building agent systems and LLM interactions.
* Example: `uv add microsoft-agents` — this will pull the latest version.
* For agent-specific guidance, refer to Agent Framework documentation and examples in the repository's prompt files (`.github/prompts/`).
