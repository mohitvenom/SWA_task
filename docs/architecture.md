# ForgeAI Architecture

## Project Vision
ForgeAI aims to be an autonomous software engineering agent that can understand natural-language tasks, modify a codebase, run tests, and open GitHub Pull Requests. It is built to support a $0 development path through local models and mocked LLM components.

## System Boundaries
ForgeAI interacts with external systems across well-defined boundaries:
- **LLM Abstraction (OmniRoute)**: Interface for language model inference.
- **Docker Sandbox**: Secure execution environment for analyzing, modifying, and testing code.
- **GitHub**: Source of truth for repositories and destination for pull requests.

## Major Components
The system is organized into a modular monolith with the following core packages:
- `api`: FastAPI application exposing web endpoints.
- `agents`: Orchestration and execution logic for AI agents (future).
- `llm`: Abstractions for language model interactions, specifically interfacing with OmniRoute (future).
- `repository`: Codebase ingestion and analysis.
- `tools`: Callable functions used by the agents.
- `sandbox`: Abstraction for the secure execution environment.
- `validation`: Verification logic (tests, linting).
- `git` / `github`: Version control and repository management.
- `config`: Centralized application configuration.
- `evaluation`: Framework to evaluate model performance on tasks.
- `policies`: Operational policies for agents.
- `models`: Shared Pydantic data models.

## Dependency Direction
Dependencies must flow inward towards domain logic. The API, GitHub integration, and LLM implementations are external adapters. The core agents and workflow logic should depend on interfaces (dependency inversion), not on concrete implementations.

## LLM Abstraction
ForgeAI interacts with language models through a provider-agnostic internal abstraction (`LLMClient`). 

**Why we don't depend on provider SDKs:**
Directly depending on vendor-specific libraries (like the `openai` or `anthropic` Python packages) couples the application to their release cycles, type definitions, and structural changes. Instead, ForgeAI defines its own domain models (`LLMRequest`, `LLMResponse`, `LLMMessage`) and requires all integrations to adapt to this internal interface.

**Provider Adapter Pattern:**
- **OmniRouteAdapter**: The primary LLM integration uses an HTTP-based adapter connecting to the OmniRoute proxy. It translates internal requests into OpenAI-compatible HTTP requests and maps HTTP/API errors back into domain-specific exceptions (e.g., `LLMRateLimitError`, `LLMAuthenticationError`).
- **MockLLMProvider**: Used extensively in testing. It provides deterministic responses and simulates failures without network calls or real API keys.
- **Future Providers**: This pattern allows seamless future integration of local models (e.g., Ollama, vLLM) or sophisticated model routing/fallback chains without changing core application logic.

## Agent Orchestration
ForgeAI relies on an explicit, state-machine-driven orchestrator rather than a generic agent framework.

**Key Concepts:**
- **AgentSession**: Tracks the execution flow for a specific task, containing an in-memory history of `AgentStep` actions for auditability.
- **StateMachine**: Enforces valid transitions between explicitly modeled `AgentState`s (e.g. `PENDING`, `RUNNING`, `THINKING`, `COMPLETED`, `FAILED`).
- **Orchestrator**: Injects the `LLMClient` via DI and controls the reasoning loop. It mandates structured JSON `AgentDecision` outputs from the LLM, parses them using Pydantic, and handles gracefully all failures such as max iterations, malformed LLM responses, and invalid transitions.

## Repository Intelligence
Before an agent attempts to plan or modify code, it utilizes the `RepositoryScanner` to build a structured, deterministic `RepositorySnapshot`.
- **AST Parsing**: The system uses the Python `ast` module to statically extract classes, functions, async functions, imports, and heuristics for test suites and entry points.
- **Determinism and Security**: Scanning avoids running any repository code, rigorously excludes secrets (like `.env`), and respects `.gitignore`. This ensures reproducible, secure snapshots without requiring LLM inference.

## Planning Agent
The `PlanningAgent` bridges the gap between the `RepositorySnapshot` and task execution. It reads the deterministic repository context and the natural language task to generate a strongly-typed, JSON-validated `EngineeringPlan`.
- **Structured Output**: Uses Pydantic to ensure plans contain explicitly separated facts, assumptions, and actionable steps, preventing unconstrained LLM hallucinations.
- **Context Selection**: Intelligently selects a subset of repository facts (based on simple keyword matches, test suites, and configurations) to avoid overloading the LLM context window.
- **Read-Only**: The planner executes no code, mutates no files, and strictly treats repository content as untrusted data to mitigate prompt injection risks.

## Test Strategy Agent
The `TestStrategyAgent` designs the validation strategy for an engineering task, sitting between the `PlanningAgent` and the `CodingAgent`.
- **Explicit Test Planning**: Consumes the `EngineeringTask`, `EngineeringPlan`, and `RepositorySnapshot` to explicitly map task acceptance criteria to structured `TestCase` specifications.
- **Hallucination Prevention**: Deterministically validates that proposed existing tests actually exist in the repository snapshot.
- **Read-Only**: The agent solely plans validation logic. It does not execute commands, modify test files, or run tests itself; it merely outputs a validated `TestStrategy` JSON object.

## Failure Diagnosis Agent
When validation fails after an implementation or repair cycle, ForgeAI invokes the `FailureDiagnosisAgent` to produce a structured `FailureDiagnosis` and optional `RepairPlan`.
- **Evidence-Based Reasoning**: The agent diagnoses from supplied validation evidence only (stdout, stderr, exit codes). It explicitly distinguishes the observed symptom from the underlying root cause.
- **Infrastructure Detection**: Heuristics detect catastrophic environment failures (e.g., Docker unavailability) before invoking the LLM, short-circuiting to an `INFRASTRUCTURE_FAILURE` status and halting the repair loop.
- **Read-Only**: The `FailureDiagnosisAgent` proposes repairs but performs no mutations. `CodingAgent` remains the sole mutation authority.
- **Application Authorization**: Before any `RepairPlan` reaches the `CodingAgent`, the application deterministically validates proposed target files against `affected_files`, `excluded_files`, and shell-injection heuristics. Unauthorized or out-of-scope targets raise `RepairPlanValidationError`.
- **Bounded Repairs**: Repair iterations are capped by `max_repair_iterations` to prevent infinite loops.

## Tool System and Execution Loop
To allow agents to interact with the repository, ForgeAI uses a tightly controlled `ToolRegistry` integrated into the `AgentOrchestrator` execution loop.
- **Capability-Based**: Tools are defined with strictly typed schemas and dynamically serialized into provider-compatible structures.
- **Security Boundary**: The tool system enforces a strict `workspace_root` boundary. Any LLM attempt at path traversal (`../`) or accessing sensitive files (e.g., `.env`) is blocked at the abstraction layer via `SecurityViolationError`.
- **Execution Loop**: The orchestrator intercepts LLM tool calls, validates them against a strict capability policy, executes them deterministically, and feeds the results back to the LLM.
- **Tool Capabilities**: Tools are strictly classified into `READ_ONLY`, `MUTATION`, and `EXECUTION`. Currently, only `READ_ONLY` tools (`list_files`, `read_file`, `search_code`) are authorized for autonomous use.
- **Safe Mutation**: A suite of mutation tools (`write_file`, `edit_file`, `delete_file`) exists utilizing deterministic editing (exact match-and-replace) and atomic writes safely bounded within the workspace. These are not yet enabled for autonomous execution.

## Multi-File Mutations and ChangeSets
When multiple files need to be modified in a coordinated fashion (e.g. extracting a function and updating imports), ForgeAI models the entire transaction explicitly using a `ChangeSet`.
- **Dependency-Aware Planning**: The `PlanningAgent` proposes a `ChangeSet` encompassing explicitly requested files and any dependency-discovered files, mapping `CREATE`, `MODIFY`, and `DELETE` operations.
- **Deterministic Scope Expansion**: The `ChangeSetPolicy` intercepts the proposal and deterministically constructs the authorized scope. It applies strict limits (`coding_max_changed_files`), directory exclusions, and security bounds (e.g. `.env` rejection).
- **Post-Change Validation**: The `CodingAgent` executes changes and relies on the Git workspace for tracking. Before marking a phase `COMPLETED`, it rigorously validates that `actual_changed_files ⊆ authorized_files` and enforces completeness (e.g. files marked for deletion must not exist).

## Git Workspace Management
To support safe autonomous coding in the future, ForgeAI uses a strict `GitService` boundary.
- **Trusted Executions**: All operations are bounded to the application's trusted root using strongly-typed arguments mapped to safe `subprocess` calls. The LLM has no access to raw Git commands or shell execution.
- **Explicit Change Control**: Staging requires explicit path references. Broad wildcard commands (`git add .`) are disabled, and sensitive files (e.g. `.env`) are explicitly blacklisted from staging.
- **Commit Safety Invariant**: The system strictly guarantees that only explicitly requested paths are permitted to be committed (`COMMITTED FILES <= EXPLICITLY REQUESTED FILES`). It intercepts unrelated staged changes and safely rejects the commit to prevent accidental file inclusions.
- **Checkpoints & Rollbacks**: A `WorkspaceCheckpoint` explicitly represents a **clean committed repository state**. It does not snapshot untracked files or dirty tracked changes. Checkpoints can ONLY be created from a pristine workspace. Rollback restorations enforce strict preconditions: they refuse to execute if uncommitted tracked changes exist, and they proactively detect and refuse restoration if any untracked path conflicts with the checkpoint's commit tree (including ancestor/descendant directory overlaps), preventing silent overwrites. Checkpoint objects are structurally validated (valid commit hash, valid commit type, valid branch, and branch/commit ancestor consistency) prior to any checkout/reset operation, though true transactional semantics across multiple Git commands are not claimed. Non-conflicting untracked files are preserved; conflicting untracked paths cause restoration to fail safely.

## Sandbox Execution Environment
To eventually run commands (like tests or linters), ForgeAI utilizes a `SandboxManager` abstraction.
- **Disposable Containers**: Backed natively by the `docker` CLI, it spins up ephemeral containers to execute commands.
- **Strict Security Limits**: Enforces CPU/Memory limits, timeouts, output truncation, dropped capabilities, and disables network access by default.
- **Workspace Isolation**: Only mounts the explicit task workspace, preventing access to the host filesystem.

## Dependency & Environment Intelligence
When validation fails, ForgeAI's `DependencyDiscovery` and `EnvironmentIntelligenceAgent` (Phase 16) provide structured, evidence-based analysis of the project's dependency and runtime state to distinguish *code failures* from *environment failures*.

```
Validation Failure
      ↓
Failure Diagnosis
      ↓
Environment Intelligence
      ↓
EnvironmentDiagnosis
      ↓
Repair Decision
```

- **Deterministic First**: Python version, declared dependencies, installed packages, and lockfile presence are all discovered without LLM assistance via `sys`, `importlib.metadata`, `tomllib`, `configparser`, and direct filesystem scanning.
- **Provenance**: Every `DeclaredDependency` carries its `source` (PYPROJECT, REQUIREMENTS, SETUP_CFG, PIPFILE) and `source_file`. Multiple declarations of the same package from different files remain as separate objects.
- **Fact vs Inference**: `EnvironmentFact.is_deterministic=True` means the fact was established without LLM reasoning. `is_deterministic=False` flags LLM-generated inferences. These are stored in separate `facts` and `inferences` lists on `EnvironmentDiagnosis`.
- **Read-Only**: `DependencyDiscovery` and `EnvironmentIntelligenceAgent` perform no mutations. No package installation, no file modification, no subprocess execution. Installed packages are detected via `importlib.metadata` only.
- **Secrets Protection**: `EnvironmentSnapshot` contains no fields for API keys, tokens, passwords, or environment variable values. The LLM receives only pre-computed `EnvironmentFact` objects.
- **Application Authorization**: `EnvironmentDiagnosis` is a structured report, not an authorization to install packages or mutate environment configuration. Future phases may introduce controlled environment mutation with explicit authorization.

## Task Memory and Execution History
To provide contextual continuity across distinct tasks on the same repository, ForgeAI tracks past runs using structured local memory.

- **Context, Not Authority**: Memory is strictly treated as historical context. It is never used to bypass the `ChangeSetPolicy`, authorize tool capabilities, validate paths, or approve sandbox commands.
- **Graceful Degradation**: Memory failures (e.g., unavailable SQLite file) fail open. The orchestrator continues task execution without historical context rather than rolling back or crashing the application.
- **Application Level Persistence**: Data is persisted at the application level (e.g., `~/.forgeai/memory.db`), completely isolating the agent's memory database from the target codebase.

## Future Concepts
- **Multi-agent Orchestration**: We will build custom orchestration logic rather than relying on external frameworks (no LangChain/AutoGen).
- **OmniRoute Boundary**: The LLM provider will be completely decoupled behind an internal abstraction interface, facilitating free-tier and local model testing.
- **Sandbox Boundary**: The system will isolate untrusted repository code in a restricted Docker environment.
- **Persistence Strategy**: Relational database (using SQLAlchemy/SQLModel) will store state, tasks, and historical agent traces.
- **Security Model**: The system relies on least privilege. The sandbox executes code as a non-root user. Keys are loaded via environment variables and never exposed to the agents.
- **Observability and Evaluation**: All agent reasoning and actions will be deterministically logged and evaluated against reference tasks.
