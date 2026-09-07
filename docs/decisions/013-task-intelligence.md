# 013 - Task Intelligence

## Context
ForgeAI aims to autonomously execute software engineering tasks based on natural-language user requests. A raw user request is often imprecise, lacking explicit requirements, constraints, or clarity on ambiguities. Treating these vague requests as facts directly in the PlanningAgent leads to incorrect assumptions, over-scoped modifications, or unsafe behaviors.

## Problem
Currently, the PlanningAgent receives a raw string description of the task and a repository snapshot, and must deduce the engineering requirements while simultaneously mapping them to repository code. If a request is ambiguous (e.g., "Fix the login problem"), the PlanningAgent might guess the intent (e.g., assuming it means fixing a specific database schema when the user just meant fixing a UI typo). We need a distinct layer to parse *what* the user wants before figuring out *how* to implement it in the repository.

## Decision
We will introduce a **Task Intelligence** layer (`TaskIntelligenceAgent`) that precedes the `PlanningAgent`. It will:
1. Accept the raw user request.
2. Produce a structured `EngineeringTask` containing explicitly separated requirements, acceptance criteria, constraints, assumptions, and ambiguities.
3. Not perform any repository scans itself, to cleanly separate the concern of "understanding user intent" from "technical planning within the codebase."

## Chosen Approach
- **Domain Models**: Defined `EngineeringTask`, `TaskAmbiguity`, `TaskRiskLevel`, `AmbiguitySeverity`, and `TaskIntelligenceStatus` in `models.py`.
- **TaskIntelligenceAgent**: A read-only agent that parses the user prompt into structured JSON using `LLMClient`.
- **Application Validation**: Hard-coded deterministic rules (e.g., a `BLOCKING` ambiguity forces the status to `NEEDS_CLARIFICATION`, preventing the task from being blindly passed to the PlanningAgent).
- **PlanningAgent Integration**: The `PlanningAgent` was updated to optionally accept an `EngineeringTask` instead of just an `AgentTask`, allowing it to consume the parsed requirements and constraints.

## Alternatives Considered
- **Combine intent parsing into PlanningAgent**: This violates the separation of concerns and complicates the prompt, making the model juggle repository context and requirement extraction simultaneously.
- **Give TaskIntelligenceAgent repository context**: Decided against this. It would duplicate the expensive repository scanning process and blend the "what" with the "how", contradicting the architectural separation.

## Consequences
- **Positive**: Clearer distinction between inferred facts and assumptions. The system can now gracefully pause and ask for clarification if a blocking ambiguity is detected, rather than failing mid-execution or corrupting code.
- **Negative**: Adds a slight latency overhead to the start of every task due to an extra LLM call.

## Security Implications
The `TaskIntelligenceAgent` is completely read-only and isolated from any tools. It cannot mutate files, execute commands, alter Git state, or modify policies. Malformed outputs result in a safe failure (`TaskIntelligenceParseError`).

## Integration with PlanningAgent
The orchestration flow is updated so the `EngineeringTask` is generated first, then passed to the `PlanningAgent` alongside the `RepositorySnapshot`. The original request is preserved in `EngineeringTask.original_request` for full traceability. Backward compatibility is maintained as `PlanningAgent` accepts both `AgentTask` and `EngineeringTask`.

## Ambiguity Handling
Ambiguities are explicitly mapped with severity levels. `BLOCKING` ambiguities immediately halt the automated flow (setting status to `NEEDS_CLARIFICATION`) before any planning or coding occurs.

## Risk Classification
Tasks are classified by risk (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). Currently, this serves as advisory metadata, though future phases might use it to enforce tighter sandboxing or mandatory human review.

## Testing Strategy
- Unit tests verify that clear tasks yield `READY`.
- Unit tests verify that blocking ambiguities yield `NEEDS_CLARIFICATION`, enforcing the deterministic rule.
- Unit tests ensure failures (e.g., LLM errors, JSON decode failures) are cleanly caught and wrapped in domain errors.
