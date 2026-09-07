# 015 - Failure Diagnosis and Intelligent Repair

## Status
Accepted

## Context
ForgeAI must be capable of diagnosing validation failures (e.g., failing tests) and generating a targeted repair plan without granting unlimited mutation autonomy to the LLM. Previously, the `CodingAgent` both interpreted validation output and directly mutated code in a single loop, risking uncontrolled changes or hallucinated success. We need a dedicated diagnostic layer.

## Decision
1. **Separation of Responsibility**: Introduce `FailureDiagnosisAgent`, a strictly read-only component that answers "Why did this fail and how do we fix it?" without having any file mutation tools.
2. **Evidence-Based Reasoning**: The diagnosis must trace the validation evidence (stdout, stderr, exit codes) and differentiate the symptom (e.g., "AssertionError") from the root cause.
3. **Infrastructure Failure Distinction**: The agent and application heuristics identify infrastructure failures (e.g., Docker unavailability or test harness crashes) and halt the repair loop, preventing arbitrary code modifications for environment issues.
4. **Application Authorization**: `FailureDiagnosisAgent` outputs a structured `RepairPlan`. The application deterministically validates the plan against `affected_files`, exclusions, and shell-injection checks before passing it to `CodingAgent` for execution.
5. **Bounded Loop**: Repair attempts are bounded by maximum iteration limits, and validation is deterministically controlled by the application, ensuring the LLM cannot simply declare its own success.

## Consequences
- **Positive**: Strict separation of diagnostic reasoning and mutation authority enhances security and predictability. The LLM cannot bypass coding policies.
- **Positive**: Improved reliability during infrastructure failures.
- **Negative**: Increases orchestration complexity as validation and repair now span multiple components.
- **Known Limitations**: Repeated identical semantic failures without exact string matching might not be caught until the iteration limit, though bounds protect against infinite loops.
