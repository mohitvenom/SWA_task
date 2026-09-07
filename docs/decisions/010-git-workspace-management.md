# 010 - Git Workspace Management

## Context
In Phase 10, ForgeAI requires the ability to safely track and revert changes using Git before the Coding Agent is permitted to autonomously modify the workspace (Phase 11). We need a mechanism to securely branch, stage, commit, diff, and rollback files programmatically without exposing raw subprocess control or arbitrary shell access to the LLM.

## Decision
We implemented a strict, typed `GitService` abstraction (`GitCLIWorkspaceService`) using Python's `asyncio.create_subprocess_exec` to wrap Git commands securely.

- **Trusted Workspace Boundary**: Git operations only execute inside a trusted path defined by the application. Absolute paths and path traversals (`../`) are intercepted and blocked before they ever touch the Git subprocess.
- **Explicit Staging & Commit Invariant**: The LLM agent will never have access to `git add .` or `git add -A`. Staging requires a deterministic list of explicit paths. Commits strictly verify that no pre-staged unrelated files are included, guaranteeing that only explicitly requested paths are permitted to be committed.
- **Sensitive File Protection**: Hardcoded rules block staging of `.env` files, `.pem` keys, and similar secrets, even if they aren't explicitly caught by `.gitignore`.
- **Branch Strategy**: Branch names are explicitly sanitized and constructed internally (e.g., `forgeai/task/<task_id>`). The agent cannot dictate arbitrary branch names or inject parameters.
- **Checkpoints and Rollbacks**: `WorkspaceCheckpoint` represents a **clean committed repository state**. Checkpoint creation requires a 100% clean workspace. Checkpoint restoration enforces strict validation (checking commit type, branch existence, and branch/commit ancestor consistency) and preconditions (rejecting if uncommitted tracked changes exist, or if an untracked file conflicts with the checkpoint tree). Rollbacks use `git reset --hard` but explicitly avoid `git clean -fd`; non-conflicting untracked files are preserved, and conflicting untracked paths cause restoration to fail safely.
- **Agent Separation**: This service represents backend infrastructure. None of these operations are exposed as Tools yet. The AgentOrchestrator remains strictly Read-Only.

## Rationale
- AI coding errors are guaranteed. If a Coding Agent deletes a critical module or botches an edit, we must have deterministic mechanisms to rollback before attempting another fix. 
- By building this abstraction layer first, we prevent arbitrary shell injection vulnerabilities. The LLM must communicate using strongly typed domain objects (`GitChange`, `GitCommit`), avoiding brittle shell string parsing.
- Introducing Git now allows integration of "edit sessions" in the upcoming Coding Agent phase.

## Consequences
- We now have robust workspace isolation via Git branching.
- We have the infrastructure to manage change rollbacks programmatically.
- This completes the foundation necessary for autonomous coding.

## Known Limitations
- The patch size is deliberately capped via `git_max_diff_bytes` to prevent massive LLM context blowouts. Truncated diffs will only report statistical changes beyond that threshold.
- Remote repository operations (cloning, pushing, PR creation) are not yet implemented. This system currently assumes the local workspace is already provisioned by the application.
