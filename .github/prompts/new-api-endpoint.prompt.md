---
mode: agent
description: Scaffold a new FastAPI endpoint with schemas, router, service, and tests (TDD-first).
---

# New API Endpoint

You are scaffolding a new FastAPI endpoint for this project. Follow test-driven development — write tests first, then implement.

## Gather Requirements

Before writing code, ask the user:

1. **Resource name** (e.g., "items", "users", "reports")
2. **HTTP operations** needed (GET list, GET by ID, POST create, PUT update, DELETE)
3. **Request/response fields** and their types
4. **Authentication required?** (yes/no)
5. **Any relationships** to existing resources?

## Implementation Order

### Step 1: Tests (write first)

Create `tests/test_<resource>.py` with tests for:
- Success responses (2xx) for each operation
- Validation errors (422) for bad input
- Not found (404) for missing resources
- Authentication (401) if auth is required

Use `httpx.AsyncClient` with the app's test fixtures. Follow the arrange-act-assert pattern.

### Step 2: Pydantic Schemas

Create request/response models in `src/template_repository/schemas/<resource>.py`:
- `<Resource>Create` for POST request body
- `<Resource>Update` for PUT request body
- `<Resource>Response` for all responses
- Use explicit type hints and field validators where needed

### Step 3: Router

Create `src/template_repository/routers/<resource>.py`:
- One `APIRouter` with a descriptive prefix and tag
- Async route handlers
- Proper status codes (201 for create, 204 for delete)
- Dependency injection for services

### Step 4: Service Layer

Create `src/template_repository/services/<resource>.py`:
- Business logic separated from HTTP concerns
- Async functions with type hints
- Raise appropriate exceptions for error cases

### Step 5: Register Router

Add the new router to `src/template_repository/main.py`.

### Step 6: Run Tests

Run `uv run pytest -W error` to verify everything passes.
