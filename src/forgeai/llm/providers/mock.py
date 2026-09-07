"""Mock LLM provider for testing."""

from typing import Callable

from forgeai.llm.client import LLMClient
from forgeai.llm.models import LLMRequest, LLMResponse, LLMUsage


class MockLLMProvider(LLMClient):
    """A mock LLM provider for testing without making network calls."""

    def __init__(
        self,
        default_response: str = "This is a mock response.",
        response_factory: Callable[[LLMRequest], LLMResponse] | None = None,
        simulate_error: Exception | None = None,
    ) -> None:
        """
        Initialize the mock provider.

        Args:
            default_response: Default text to return if no factory is provided.
            response_factory: A callable to generate custom responses.
            simulate_error: An exception to raise for simulating failures.
        """
        self.default_response = default_response
        self.response_factory = response_factory
        self.simulate_error = simulate_error
        self.call_count = 0
        self.last_request: LLMRequest | None = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        self.last_request = request

        if self.simulate_error:
            raise self.simulate_error

        if self.response_factory:
            return self.response_factory(request)

        return LLMResponse(
            content=self.default_response,
            model=request.model,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            finish_reason="stop",
            request_id=f"mock-req-{self.call_count}",
        )
