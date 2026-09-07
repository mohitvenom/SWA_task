# 002 - Internal LLM Abstraction

## Context
ForgeAI needs to communicate with language models. In Phase 1, we decided that the system will integrate with OmniRoute, and eventually support local models and mocked providers for testing. We need a way for the core application to generate responses from these providers without being tightly coupled to their specific SDKs (like OpenAI or Anthropic SDKs).

## Decision
We will build a provider-agnostic internal LLM abstraction (`LLMClient` protocol) and implement adapter classes (e.g., `OmniRouteAdapter`, `MockLLMProvider`) to bridge the gap between our internal domain and external provider APIs.

## Rationale
- **Dependency Inversion**: Application code depends on an internal interface (`LLMClient`), not an external vendor SDK.
- **Testability**: We can easily inject a `MockLLMProvider` in tests to achieve 100% offline, deterministic testability without mocking HTTP layers globally.
- **Future Flexibility**: We can add new providers (e.g., a LocalOllamaAdapter) in the future without changing the core business logic.
- **Standardized Error Handling**: Provider-specific HTTP errors are converted into domain-specific exceptions (e.g., `LLMRateLimitError`, `LLMAuthenticationError`), so the calling code handles standard exceptions regardless of the underlying provider.

## Alternatives Considered
- **Using LangChain or similar frameworks**: Rejected due to the project rule against speculative and heavy dependencies. We prefer owning our critical paths.
- **Directly using OpenAI Python SDK**: Rejected because it couples our application tightly to OpenAI's library structure, making it harder to implement purely mock providers or switch seamlessly to fundamentally different local model APIs if needed in the future.
- **Depending directly on `httpx` in business logic**: Rejected because it violates separation of concerns. Business logic should deal with `LLMRequest` and `LLMResponse`, not HTTP status codes and JSON parsing.

## Consequences
- We must maintain the `LLMClient` protocol and its associated models (`LLMMessage`, `LLMRequest`, `LLMResponse`).
- Adding new features (like function calling or streaming) will require updating this internal abstraction.
