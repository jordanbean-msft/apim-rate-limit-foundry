---
description: Test standards for this repository
applyTo: "**/tests/**/*.py"
---

## Test Standards

* Cover happy paths and key failure paths.
* Mock external dependencies.
* Keep tests deterministic and independent.
* Use clear arrange-act-assert structure.
* Use async tests for async behavior.
* Use `httpx.AsyncClient` for testing FastAPI endpoints.

## Expected scope

* Unit tests for config, business logic, and API contract.
* Integration tests that run locally without cloud credentials by using fake services.
