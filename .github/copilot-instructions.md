---
description: Repository-wide guidance for implementing and validating this Python project
---

## Purpose

This repository is a Python project using FastAPI, uv for package management, and Terraform for Azure infrastructure. Keep implementation simple, explicit, and testable.

## Project layout

```
src/template_repository/   # Application source code
tests/                     # Test suite
infra/                     # Terraform infrastructure-as-code
```

## Required engineering standards

- Always use uv for environment and dependency management.
- Prefer Microsoft-published and Microsoft-maintained libraries, SDKs, and tools whenever they satisfy the requirement. Use a third-party alternative only when no suitable Microsoft-published option exists, and document the reason in the pull request.
- Keep Python imports at the top of files, grouped and sorted.
- Do not use lazy imports or wrap imports in try/except blocks.
- Prefer pydantic-settings for centralized configuration.
- Use structured logging.
- Use explicit type hints on public functions and class methods.
- Keep functions small and composable.
- Favor single-responsibility Python modules: keep one primary class, interface/protocol, service, or other major component per file, and use package directories to group related components instead of placing multiple major definitions in one file.
- Use dependency injection for external services.
- Favor async interfaces for network-bound operations.

## Build and validation commands

- Sync environment: `uv sync --extra dev`
- Run lint: `uv run ruff check .`
- Run all tests: `uv run pytest`
- Enforce warning-free tests: `uv run pytest -W error`
- Run with coverage: `uv run pytest --cov --cov-report=xml --cov-report=term-missing`
- Run API: `uv run template-repository`

## Testing patterns

- Cover happy paths and key failure paths.
- Mock external dependencies (API calls, Azure credentials, databases).
- Keep tests deterministic and independent.
- Use clear arrange-act-assert structure.
- Use async tests for async behavior.
- Use `httpx.AsyncClient` with FastAPI's `TestClient` for API testing.
- Prefer deterministic mocks over network calls.

## Pull request quality bar

- Include tests for all newly added behavior.
- Do not merge with test warnings. Treat warnings as failures.
- Keep commit scope coherent and focused.

## Parallel development

- Use multiple code agents when work can be divided into independent, well-bounded tasks that can be implemented and validated concurrently.
- Give each agent a clear ownership boundary, expected outcome, and validation responsibility to minimize duplicated or conflicting work.
- Use a separate Git worktree and branch for each agent making code changes in parallel. Do not allow multiple agents to modify the same working tree concurrently.
- Avoid parallelizing tightly coupled changes, shared-file edits, or tasks that require sequential design decisions; use a single agent when coordination overhead or merge risk outweighs the benefit.
- Review and integrate each worktree's changes deliberately, resolve conflicts without discarding unrelated work, and run the relevant combined validation after integration.

## Work planning and progress

- When a task requires a written implementation plan, save the plan in the repository under `.github/plans/` before coding begins. Use a descriptive kebab-case filename such as `.github/plans/add-user-authentication.md`.
- Write plans as Markdown checklists with small, independently actionable items. Include expected files or ownership boundaries, dependencies, acceptance criteria, and validation commands where relevant.
- Keep the plan as the durable source of progress for all coding agents. Agents must read it before starting, claim or identify their assigned items, and change completed items from `- [ ]` to `- [x]` as work is finished.
- Record concise status or blocker notes directly beside unfinished checklist items so progress is understandable without relying on an agent's conversation history.
- Update the plan after meaningful progress and before an agent stops. If an agent fails or is restarted, the next agent must resume from the unchecked items and recorded notes rather than repeating completed work.
- Do not mark an item complete until its implementation and specified validation are complete. After integration, ensure the plan reflects the final state and any intentionally deferred work.

## VS Code automation

- Always provide and maintain repository-scoped VS Code tasks in `.vscode/tasks.json` for common developer operations.
- Include tasks for environment setup, building or packaging source code, running the application, running unit tests, running tests with warnings treated as errors, linting, formatting, type checking, and validating infrastructure when those operations apply to the repository.
- Use the repository's established commands and tooling in tasks, including `uv` for Python operations and Terraform commands for infrastructure. Do not duplicate build logic in task definitions when an existing script or package command can be invoked.
- Provide and maintain `.vscode/launch.json` debugger configurations for each runnable source-code entry point. Use `preLaunchTask` when setup or build work is required before debugging.
- Keep task labels stable, descriptive, and suitable for use by `preLaunchTask` and other automation. Group tasks with VS Code's standard `build`, `test`, and `none` groups, and assign sensible default build and test tasks.
- Update VS Code tasks and debugger configurations whenever development commands, entry points, required environment setup, or infrastructure validation workflows change.

## Infrastructure

- Terraform is used for Azure infrastructure under `infra/`. See `.github/instructions/terraform.instructions.md` for detailed IaC conventions.
- Format Terraform changes with `terraform -chdir=infra fmt -recursive` during development.
- A Terraform change is complete only after `terraform -chdir=infra fmt -check -recursive` and `terraform -chdir=infra validate` finish with zero errors and zero warnings. Initialize with `terraform -chdir=infra init -backend=false` first when required.
- Azure Developer CLI (`azd`) orchestrates provisioning and deployment.
- Remote state is stored in Azure Blob Storage (configured via `provider.conf.json`).
- azd environment variables flow into Terraform via `main.tfvars.json` placeholder substitution (`${VAR_NAME}` syntax). Core variables (`AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_LOCATION`, `AZURE_ENV_NAME`, `AZURE_RESOURCE_GROUP`, `AZURE_PRINCIPAL_ID`) are set during `azd init` or `azd env set`.
- Terraform outputs (SCREAMING_SNAKE_CASE) are captured by azd and become environment variables for deployment and application runtime.
- Do not use Azure Verified Modules (`Azure/avm-res-*`). Define Azure resources directly with `azurerm_*`, using `azapi_*` only when the required resource or property is not supported by `azurerm`. Look up the latest stable provider versions on the Terraform registry.
- The resource group is always pre-created and passed in — never create it in Terraform.
- Azure Deploy If Not Exists policies manage private DNS zone groups and virtual network links. Every `azurerm_private_endpoint` must include `lifecycle { ignore_changes = [private_dns_zone_group] }`, and Terraform must not create or manage private DNS zone groups.
