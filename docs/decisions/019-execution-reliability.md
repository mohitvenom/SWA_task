# 019: Execution Reliability & Hardening

## Status
Accepted

## Context
ForgeAI previously experienced persistent runtime failures across various execution environments (e.g., `asyncio`, `trio`) when invoking subprocesses like Git commands and Docker Sandbox operations. The direct use of `asyncio.create_subprocess_exec` tightly coupled the execution flow to the `asyncio` event loop, causing `RuntimeError: no running event loop` when running tests or operations under `pytest-anyio` configured for other backends (like `trio`). Additionally, failures during the coding agent review process would leave the Git workspace in a dirty state because the rollback mechanism (`GitCLIWorkspaceService.restore_checkpoint`) enforces a strict precondition that the tracked workspace must be clean before a hard reset. 

## Decision
1. **Abstract Subprocess Execution:** We created `ProcessRunner` in `src/forgeai/execution/runner.py`, which utilizes `anyio.open_process` to provide a framework-agnostic, async-safe subprocess execution layer. This completely decouples our execution models from `asyncio`-specific primitives.
2. **Refactor Services:** `DockerSandbox` and `GitCLIWorkspaceService` have been updated to replace direct `asyncio.create_subprocess_exec` calls with `ProcessRunner.run`.
3. **Safe Rollback Sequences:** We updated `CodingAgent._rollback` to explicitly discard uncommitted tracked changes (using `GitCLIWorkspaceService.rollback_files`) *before* attempting `restore_checkpoint`. This satisfies the precondition that a rollback must not implicitly destroy uncommitted user work, while allowing the agent to clean up its own failed modifications safely.
4. **Test Mocks:** Updated unit tests to correctly mock the higher-level `ProcessRunner.run` rather than the lower-level `asyncio` methods, ensuring tests reflect the true abstracted behavior.

## Consequences
- **Positive:** Subprocesses run deterministically and safely under any `anyio`-supported event loop backend (`asyncio`, `trio`). The `test_coder_review.py` integration tests now correctly roll back dirty states on mock failures, allowing tests to pass reliably. The test suite has been completely stabilized.
- **Negative:** Added a direct dependency on `anyio` (already present via `pytest-anyio`, but now explicitly required for runtime execution), introducing a slight abstraction penalty over raw `asyncio`.
