# 009 - Repository Mutation Tools

## Context
In Phase 9, ForgeAI required the ability to mutate the repository securely (creating, editing, and deleting files). These operations represent a significant escalation in capability from the Phase 7 read-only toolset. 

## Decision
We implemented a strict mutation layer with three specific tools: `WriteFileTool`, `EditFileTool`, and `DeleteFileTool`.

- **Workspace Boundaries**: All mutation tools rely exclusively on the `resolve_safe_path` utility. This prevents absolute paths, `../` directory traversals, and symlink escapes from breaching the bounds of the trusted workspace.
- **Strict Editing Semantics**: `EditFileTool` performs an exact string replacement (`content.replace(expected_text, replacement_text)`). It requires the `expected_text` to be found exactly `expected_count` times. We intentionally avoided fuzzy matching or LLM-driven patch interpretation to ensure edits are completely deterministic.
- **Atomic Operations**: Both `write_file` and `edit_file` create a temporary file adjacent to the target and then use `os.replace()` to atomically overwrite the target. This ensures we do not leave corrupted or partially written files on disk if the process crashes or fails.
- **Authorization Separation**: We introduced a `ToolCapability` enum (`READ_ONLY`, `MUTATION`, `EXECUTION`) to `ToolDefinition`. Although these mutation tools are available in the registry, the `AgentOrchestrator` explicitly blocks their execution during autonomous sessions. **Schema discoverability does not equal authorization.**

## Rationale
- **Security First**: AI code generation is prone to subtle errors. Exact search-and-replace forces the LLM to verify what it is changing, minimizing accidental destruction of context it did not read.
- **Separation of Concerns**: By implementing the tools before enabling the agent to use them, we can rigorously test the filesystem constraints (edge cases, invalid paths, missing files) without debugging complex LLM agent loops simultaneously.
- **Rollback Safety**: Atomic writes guarantee that if an operation fails midway (e.g. out of memory, or process kill), the original file remains fully intact. While Git will be the primary rollback layer, atomic filesystem operations provide crucial local resilience.

## Consequences
- The system now possesses the raw mechanisms required for a Coding Agent to modify files.
- The `AgentOrchestrator` remains safely constrained to a read-only policy.
- Future phases (like Phase 10) can begin enabling these capabilities for specific agent personas once Git rollback logic is integrated.
