# Instructions for AI Coding Agents (ForgeAI Project)

These instructions apply to all AI agents writing or modifying code in the ForgeAI project.

## Architecture
- Understand the existing architecture before changing it.
- Maintain a **modular monolith** design. Avoid creating microservices.
- Ensure strict separation of concerns (e.g., API layer must not contain business logic).
- Future integration points (OmniRoute, Docker Sandbox, GitHub) should be cleanly abstracted using dependency inversion.

## Coding Style
- Write clean, maintainable Python 3.12+ code.
- Follow PEP 8 guidelines. Use `ruff` for formatting and linting.
- Avoid speculative abstractions. Do not implement features until they are needed.

## Type Safety
- All Python code must be fully type-hinted.
- The project enforces `strict = true` in `mypy`. Ensure no `Any` is used where a specific type can be inferred or defined.

## Testing
- Write comprehensive unit tests for all business logic using `pytest`.
- Ensure new code does not break existing functionality. Run the test suite before submitting changes.
- Tests should mock external boundaries (LLM API, Sandbox, GitHub) and avoid external side effects.

## Security & Secrets
- Never commit actual secrets or credentials to the repository.
- Use `.env.example` to document required configuration. Load configuration via Pydantic Settings.

## Dependencies
- Only introduce new dependencies when there is a clear architectural reason.
- Do NOT introduce frameworks like LangChain, LangGraph, CrewAI, or AutoGen. We maintain our own orchestration and LLM abstractions.
- All core operations should support a **$0 development/inference path** (e.g., local models, mocked APIs).

## Logging & Observability
- Use standard Python `logging` or structured logging (when adopted). Ensure deterministic logs where possible to aid debugging.
- Do not suppress errors merely to make checks pass.
