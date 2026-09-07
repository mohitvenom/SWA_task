# 005 - Planning Agent

## Context
In Phase 5, ForgeAI required the ability to take a natural-language task and a deterministic `RepositorySnapshot` and generate an actionable, structured plan. This planning step needs to occur *before* any tools are executed or code is mutated.

## Decision
We implemented a dedicated, read-only `PlanningAgent` that strictly returns a Pydantic-validated `EngineeringPlan`.
- **Structured Output**: The LLM is prompted with the JSON schema of `EngineeringPlan` to enforce strict formatting, including explicit separation of `discovered_facts`, `assumptions`, and `proposed_changes`.
- **Context Selection**: Instead of injecting the entire repository into the context window, the planner uses a deterministic algorithm to filter the `RepositorySnapshot` (including important files, test suites, and simple keyword-matched symbols/files).
- **Read-Only execution**: The Planning Agent has no tool access and cannot execute code or make changes.

## Rationale
- **Separation of Concerns**: Planning and execution require different prompts, contexts, and validation mechanisms. Isolating the planner ensures that we can validate the plan structure before letting an execution agent mutate the repository.
- **Structured Output**: Enforcing a strict schema prevents the LLM from outputting ambiguous text, ensuring the orchestrator (or a human reviewer) can programmatically inspect the proposed steps, dependencies, and validation requirements.
- **Prompt Injection Defense**: By treating the repository snapshot strictly as data and providing no mutation tools to the planner, we limit the blast radius if the LLM is confused by adversarial repository contents.

## Consequences
- The planner relies heavily on the quality of the LLM's JSON generation capabilities. If the LLM generates invalid JSON, the orchestrator will catch a `PlanValidationError` rather than proceeding with a broken string.
- Context selection is currently basic keyword matching. As the project scales, this may need to be enhanced with semantic search, though that is deferred to future phases to avoid premature complexity.
