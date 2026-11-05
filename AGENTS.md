# Copilot Agent Guide

Use this guide to choose the right Copilot agent type for common development tasks.

## Agent Selection

| Task | Agent | Why |
|------|-------|-----|
| Understand a module or flow | **Explore** | Fast, read-only, parallel research |
| Find usages / trace a symbol | **Explore** | Searches across many files quickly |
| Implement a feature or fix | **General-purpose** | Full tool access, high-quality reasoning |
| Scaffold a new endpoint/test | **General-purpose** | Needs file creation and editing |
| Run tests / builds / lints | **Task** | Returns concise pass/fail; full output on error |
| Install dependencies | **Task** | Simple command execution |
| Review a diff or PR | **Code-review** | High signal-to-noise; won't modify code |
| Security audit of changes | **Code-review** | Surfaces bugs, vulnerabilities, logic errors |

## Tips

- **Explore** is stateless — provide full context in each prompt.
- **Task** keeps main context clean — use for any command where you only need success/failure.
- **General-purpose** has the strongest reasoning — use for complex multi-step work.
- **Code-review** never modifies files — safe for auditing changes.
- Launch multiple **Explore** or **Code-review** agents in parallel for independent investigations.
- Use **Task** for builds and tests so verbose output doesn't clutter your conversation.

## Key Paths

| Area | Path |
|------|------|
| Application source | `src/template_repository/` |
| Tests | `tests/` |
| Infrastructure | `infra/` |
| Copilot instructions | `.github/instructions/` |
| Copilot prompts | `.github/prompts/` |
| Architecture docs | `ARCHITECTURE.md`, `docs/` |
