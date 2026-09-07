"""Internal LLM client protocol."""

from typing import Protocol

from forgeai.llm.models import LLMRequest, LLMResponse


class LLMClient(Protocol):
    """Protocol defining the required interface for all ForgeAI LLM providers."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Generate a response from the LLM based on the given request.

        Args:
            request: The generation parameters and conversation history.

        Returns:
            The generated response with content and metadata.

        Raises:
            LLMError: If any provider-agnostic error occurs during generation.
        """
        ...
