# 007 - Tool Execution Loop

## Context
In Phase 7, ForgeAI needed a safe, reliable execution loop connecting the LLM, the ToolRegistry, and the AgentOrchestrator to perform multi-step read-only repository analysis.

## Decision
We implemented a stateful tool execution loop within the `AgentOrchestrator`:
- **Domain Models**: Expanded `LLMMessage` and `LLMResponse` to natively support `tool_calls` and `tool_call_id`, remaining provider-agnostic.
- **Validation**: Every tool call requested by the LLM is intercepted. The orchestrator checks if the tool is registered and permitted by the phase policy (only `list_files`, `read_file`, and `search_code` are allowed).
- **Execution**: Validated tools are executed deterministically. Results or errors are collected and appended as `role="tool"` messages to the conversation history.
- **Error Handling**: 
  - Malformed LLM responses and generic tool failures do not crash the session; instead, they return error payloads to the LLM so it can learn and retry.
  - Security boundaries (e.g. `SecurityViolationError` from path traversal) are treated as hard session failures to prevent adversarial exploitation.
- **Iteration Limits**: The orchestrator enforces a hard `max_iterations` limit to prevent infinite reasoning loops.

## Rationale
- **Security-First**: The LLM output is entirely untrusted. By validating against the `ToolRegistry` and a hardcoded whitelist of allowed tools before execution, we ensure the agent cannot trick the system into calling arbitrary Python functions or forbidden tools.
- **Provider Agnosticism**: The orchestrator deals entirely in ForgeAI domain models (`LLMToolCall`, `LLMMessage`). Provider-specific JSON logic (e.g., OpenAI schemas) is isolated in `OmniRouteAdapter`.
- **Fault Tolerance**: Giving the LLM immediate feedback upon tool failure (like missing arguments) improves task success rates without needing complex recovery code.

## Consequences
- The orchestrator can now execute autonomous, multi-step investigation loops.
- Writing code, shell execution, and GitHub interaction are explicitly blocked in this phase and will require policy adjustments in future phases.
