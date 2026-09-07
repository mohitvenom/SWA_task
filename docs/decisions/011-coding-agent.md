# 011 - Autonomous Coding Agent

## Context
Phase 11 introduces the first autonomous Coding Agent. Having established the foundation in prior phases (Repository Intelligence, Git Workspace Management, Docker Sandbox, Planning Agent), the system now requires an agent capable of consuming an `EngineeringPlan`, inspecting the repository, modifying authorized files, running controlled validations, and rolling back if necessary. The system needs to ensure the LLM cannot exceed authorized budgets or bypass security paths while making autonomous edits.

## Decision
We implemented the `CodingAgent` and an accompanying `CodingSession` state machine with a centralized `CodingPolicy`.

- **CodingSession Architecture**: Distinct from `AgentSession`, this models the specialized loop of a coding task with tracking variables for iterations, tool calls, and repair cycles.
- **State Machine Loop**: The agent transitions through explicit phases: `INITIALIZING` -> `INSPECTING` -> `IMPLEMENTING` -> `VALIDATING` <-> `REPAIRING` -> `REVIEWING` -> `COMPLETED`/`FAILED`/`ROLLED_BACK`.
- **CodingPolicy Authorization**: Security logic is centralized. Mutation tools are restricted to the `IMPLEMENTING` phase and read-only tools to `INSPECTING`. `RunCommandTool` is restricted to `VALIDATING` and `REPAIRING`.
- **Path Confinement**: Any requested file mutation is checked against `resolve_safe_path` and strictly verified against the `affected_files` and `excluded_files` provided in the `EngineeringPlan`.
- **RunCommandTool**: We implemented an execution tool that runs strictly through the established `SandboxManager` (Docker). Arbitrary shell execution (`bash -c`) on the host is completely forbidden; the tool utilizes a hardcoded allowlist (`pytest`, `mypy`, `ruff`, etc.).
- **Validation and Repair Loop**: When a validation command yields a non-zero exit code, the agent transitions to a `REPAIRING` phase, where it receives the test output to fix the code, followed by a mandatory re-validation.
- **Git Checkpoint and Rollback**: At initialization, the agent takes a `WorkspaceCheckpoint` ensuring the workspace is clean. Any critical exception, security violation, or budget exhaustion triggers an automatic rollback of the task branch via the `GitService`.
- **Security Boundaries and Testing**: Bounded iterations prevent infinite loops. Exhaustive integration tests assert that the agent cannot traverse outside the repository, write to excluded files, or commit unauthorized files.

## Rationale
- The LLM cannot be trusted to independently govern its execution environment. Hard boundaries at the application policy level (in `CodingPolicy`) guarantee safety regardless of hallucinated LLM responses.
- Decoupling `CodingSession` from generic sessions provides the specific telemetry required for the coding domain (e.g., test loops, checkpoint hashes).
- Enforcing strict test/validation loops reduces the likelihood of the LLM pushing syntactically invalid or logic-breaking code.

## Consequences
- The platform can now autonomously fulfill `EngineeringPlan` specifications safely.
- The Git abstraction successfully protects the host from unintended destruction during autonomous loops.
- Re-running validation logic introduces potential loop-exhaustion vulnerabilities, which are strictly managed by `coding_max_iterations` and `coding_max_repair_iterations` budgets.

## Known Limitations
- The `CodingAgent` currently serves as the final authority on its own correctness. If tests pass (or if tests are not comprehensive), the agent considers the implementation complete. An independent verification layer is needed.
- Only pre-authorized files defined during the Planning phase can be edited; if the agent discovers during implementation that an extra file must be edited, it will hit a security violation.
