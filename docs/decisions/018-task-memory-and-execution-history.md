# Phase 18: Task Memory and Execution History

## Objective
Implement structured task memory and execution history to allow ForgeAI to contextualize its actions based on past repository tasks, without letting memory become an authorization boundary.

## Architecture and Constraints
1. **Memory as Context, Not Authority**: Memory strictly remains context. It never authorizes filesystem access, tool capabilities, git operations, or sandbox execution. All operations are re-validated by the current application policy.
2. **Graceful Degradation**: Memory failure (e.g. SQLite database inaccessible) must never trigger a repository rollback or system failure. The agent must continue execution without historical context.
3. **Application Level Storage**: Memory persistence must be handled at the application level (`~/.forgeai/memory.db`) rather than polluting the target repository.

## Implementation Details
1. **SQLiteMemoryStore**: Uses a local SQLite database to persist execution records and events. Employs broad exception handling in initialization and querying to ensure isolated failures.
2. **MemoryContextBuilder**: Queries the store and formats past execution records into a string context to be injected into the LLM prompts.
3. **ApplicationOrchestrator Integration**: Logs task lifecycle events (Planning, Coding, Validation) to the store automatically.

## Security Validations
- `MemoryContextBuilder` uses `settings.memory_enabled` to optionally bypass memory logic.
- Integration tests in `test_memory_security.py` strictly enforce that memory failures degrade gracefully and memory content does not bypass the `ChangeSetPolicy`.
