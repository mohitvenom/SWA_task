# 003 - Agent Orchestration

## Context
In Phase 3, we needed to establish the execution model for ForgeAI. The system must autonomously iterate, reasoning and interacting with the LLM to complete a given task. We need to define how the core reasoning loop works, how state is managed, and how we ensure safety (like avoiding infinite loops).

## Decision
We chose to build an explicit Python-based state-machine orchestrator from scratch rather than adopting generic agent frameworks like LangChain, AutoGen, or CrewAI.

We defined:
- **`AgentSession`**: The core state holder for a task execution instance.
- **`StateMachine`**: Enforces strict transitions (e.g., `PENDING` -> `RUNNING` -> `THINKING`).
- **`AgentOrchestrator`**: Injects the `LLMClient` (from Phase 2) and runs the execution loop. It strictly requires the LLM to return a structured JSON `AgentDecision` enforcing predictability.
- **Iteration Limits**: Hardcoded configuration bounds the maximum number of iterations an agent can make, avoiding infinite API spend loops.

## Rationale
- **Control and Transparency**: Generic frameworks abstract the execution loops in ways that can be hard to audit, debug, or evaluate strictly. For a software-engineering agent where determinism and safety (sandbox isolation) are critical, we need full control over the execution loop.
- **State Machine Benefits**: Explicit transitions make invalid flows (e.g. jumping from PENDING to COMPLETED without RUNNING) impossible, leading to fewer edge-case bugs.
- **Persistence Readiness**: Our domain models (`AgentSession`, `AgentStep`) can easily map to SQLAlchemy models in a later phase.
- **Mockability**: The orchestrator takes the `LLMClient` via DI, allowing us to unit-test orchestration flows entirely offline with `MockLLMProvider`.

## Consequences
- We must maintain our own prompting strategy and loop control logic.
- We must explicitly parse and handle malformed JSON from the LLM, whereas frameworks sometimes handle retries transparently.
