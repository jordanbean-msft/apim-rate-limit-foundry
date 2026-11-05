---
description: Python coding standards for this repository
applyTo: "**/*.py"
---

## Python Standards

* Use Python 3.12-compatible syntax and typing.
* Keep imports at file top, grouped and sorted.
* Avoid broad except blocks unless translating errors with clear context.
* Prefer explicit type hints on public functions and class methods.
* Keep functions small and composable.
* Use dependency injection for external services.
* Prefer Microsoft-published and Microsoft-maintained libraries and SDKs whenever they provide the required functionality. Use third-party alternatives only when no suitable Microsoft option exists.
* **For LLM interactions, use Microsoft Agent Framework** (`microsoft-agents`). Never use `azure-ai-projects` directly if Agent Framework provides the needed functionality.

## Module organization

* Favor single-responsibility files with one primary class, interface/protocol, service, model, or other major component per file.
* Use package directories to group related components rather than placing multiple unrelated or independently reusable definitions in the same module.
* Keep small private helpers, closely coupled types, and module-level constants with their owning component when separating them would reduce clarity.
* Name files and packages after their primary responsibility, and expose intentional public APIs through `__init__.py` only when a package-level import improves usability.

## Runtime behavior

* Route all environment reads through the settings model (pydantic-settings).
* Emit logs with stable structured context.
* Favor async interfaces for network-bound operations.
