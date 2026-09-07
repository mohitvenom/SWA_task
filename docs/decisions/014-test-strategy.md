# 014 - Test Strategy

## Context
As ForgeAI evolves into a more mature autonomous engineering agent, we need to ensure that the code it writes is robustly verified. However, determining *how* a task should be tested requires reasoning about existing tests in the repository and the task's specific acceptance criteria.

We needed to decide whether the `PlanningAgent` or the `CodingAgent` should be responsible for this, or if a new distinct layer was necessary.

## Problem
- If the `PlanningAgent` designs the tests, its prompt becomes overly complex and it blends the "how to write the feature" with the "how to test it".
- If the `CodingAgent` designs the tests, it operates in a mode where it has unrestricted mutation capabilities, increasing the risk that it writes tests that merely pass its own flawed logic or fabricates execution commands.
- We need the LLM to explicitly differentiate between existing repository tests and new tests it proposes, to ensure it doesn't hallucinate coverage.
- We must enforce that all explicitly stated `acceptance_criteria` from the user are matched with validation goals.

## Decision
We will introduce a distinct **Test Strategy layer** (`TestStrategyAgent`) that sits between the `PlanningAgent` and the `CodingAgent`.

## Chosen Approach
1. **Domain Models**: Added `TestStrategy`, `TestCase`, `TestPriority`, and `TestType` models to enforce structure.
2. **TestStrategyAgent**: A read-only agent that consumes `EngineeringTask`, `EngineeringPlan`, and `RepositorySnapshot`.
3. **Application Validation**: The agent's output is deterministically validated to ensure:
   - All `acceptance_criteria` have corresponding validation goals.
   - Any claimed `relevant_existing_tests` actually exist in the `RepositorySnapshot`.
   - Proposed validation commands are safe and do not contain shell injection operators or unauthorized executables.
4. **Risk-Awareness**: The strategy naturally incorporates the `TaskRiskLevel` from the task intelligence layer to scale the testing requirements (e.g., unit tests for low risk, regression tests for high risk).

## Alternatives Considered
- **Combining Test Strategy into PlanningAgent**: Discarded. The prompt for `PlanningAgent` is already large, and splitting out test generation makes the system easier to test and reason about.
- **Combining Test Strategy into CodingAgent**: Discarded. The `CodingAgent` holds mutation capabilities, and allowing the component that writes the code to also unilaterally decide what is "sufficiently tested" without a prior structured plan violates our security boundaries.

## Consequences
- **Positive**: Clear separation of concerns. Tests are planned based on the user's explicit acceptance criteria, independent of the implementation details of the code. We catch hallucinations (invented existing tests) deterministically.
- **Negative**: Adds another LLM call to the execution pipeline, marginally increasing task latency.

## Security Implications
The `TestStrategyAgent` is strictly read-only. It has no tools to mutate the filesystem or execute commands. The `validation_commands` it proposes are subject to deterministic string matching to filter out basic shell injections before they ever reach an executor (and ultimately, the application orchestrator still decides whether to run them).

## Limitations
This phase does not implement the actual execution of the proposed tests or autonomous repair loops; it purely generates the *strategy* and *specifications* for tests that the `CodingAgent` must later implement and the system must execute.
