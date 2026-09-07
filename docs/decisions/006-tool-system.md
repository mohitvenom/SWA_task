# 006 - Tool System

## Context
In Phase 6, ForgeAI needed a way to extend LLM capabilities via tools while strictly enforcing security, boundary isolation, and determinism. The system must allow agents to read the repository without arbitrarily executing code or escaping the workspace.

## Decision
We implemented a capability-based `ToolRegistry` and a standard `BaseTool` abstraction.
- **Typed Definitions**: Tools are defined using Pydantic (`ToolDefinition`, `ToolCall`, `ToolResult`).
- **Schema Generation**: The registry automatically translates `ToolDefinition`s into OpenAI-compatible JSON schemas.
- **Read-Only First**: We introduced three safe tools: `ListFilesTool`, `ReadFileTool`, and `SearchCodeTool`.
- **Security Boundary**: All path resolution strictly enforces the `workspace_root`. Symlink escapes, path traversal (`../`), and access to sensitive files (e.g. `.env`) trigger immediate `SecurityViolationError` exceptions.

## Rationale
- **Explicit Capabilities**: By explicitly defining tools, the agent orchestrator will be able to hand the LLM exactly the tools it needs for the current phase (e.g. reading vs writing).
- **Security**: The LLM is untrusted. Path traversal vulnerabilities are common in LLM-generated tool calls. We prevent these at the domain layer before accessing the filesystem.
- **Separation of Concerns**: Generating schemas programmatically ensures the schema the LLM sees is always perfectly in sync with the Python implementation.

## Consequences
- The LLM request model is now aware of tools via a generic dictionary format.
- Tool orchestration (loops) are still not implemented; they are deferred to Phase 7.
- Semantic search is avoided to keep the footprint lightweight. Simple python string matching scales adequately for typical single-repo workspaces.
