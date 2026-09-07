# Phase 12: Autonomous Code Review & Final Validation

## Objective
Implement an independent ReviewAgent that audits the changes made by the CodingAgent against the EngineeringPlan, ensuring plan compliance, security boundaries, and code correctness before committing.

## Architectural Changes

### 1. `ReviewAgent` Implementation
Created `ReviewAgent` as a standalone orchestration unit responsible for evaluating the final diff produced by the CodingAgent.
- **Strictly Read-Only:** The ReviewAgent has its own `ReviewPolicy` that restricts tool usage exclusively to `ToolCapability.READ_ONLY` tools. It cannot modify files or execute arbitrary commands.
- **Deterministic Severity Mapping:** We enforce a deterministic mapping from finding severities to final statuses. For instance, any `CRITICAL` finding automatically results in a `REJECTED` status, overriding the LLM if it hallucinates an `APPROVED` status.
- **Inputs:** Receives the original `AgentTask`, `EngineeringPlan`, the Git diff, the list of changed files, and the output of any validation commands run by the CodingAgent.

### 2. `CodingAgent` Integration
Integrated the ReviewAgent into the `CodingAgent` state machine as a final step before committing.
- **`CodingPhase.REVIEWING`:** Added a new state transition. Once `VALIDATING` completes, the agent enters `REVIEWING`.
- **Review Budgeting:** Introduced `review_max_iterations` to bound the review-repair cycle. The `CodingSession` now tracks `review_count`.
- **Feedback Loop:** If the reviewer returns `CHANGES_REQUIRED`, the `CodingAgent` transitions back to `CodingPhase.REPAIRING` and is provided the reviewer's findings as feedback.
- **Final Rollback:** If the reviewer returns `REJECTED`, or if the review iterations budget is exhausted, the `CodingAgent` raises a `SecurityViolationError`, forcing a rollback of all changes.

### 3. Application-Level Diff Boundary Enforcement
Before a review is even deemed valid, or a commit is processed, we ensure that the actual changed files strictly respect the `EngineeringPlan`.
- **Invariant Enforcement:** `actual_changed_files ⊆ affected_files` and `actual_changed_files ∩ excluded_files = ∅`
- This is checked programmatically in the `CodingAgent` loop. If an unauthorized file is modified, a `SecurityViolationError` is raised, triggering an immediate rollback regardless of the ReviewAgent's output.

## Security and Trust Boundaries
The ReviewAgent acts as an independent check against the CodingAgent. By utilizing separate LLM contexts and strictly read-only tools, it provides an objective assessment of the proposed implementation, minimizing the risk of the CodingAgent hallucinating success or violating architectural boundaries.

## Status
Phase 12 is successfully implemented, heavily tested, and verified via unit and integration tests.
