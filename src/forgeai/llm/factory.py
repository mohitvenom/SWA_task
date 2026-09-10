"""
LLM client factory.

Creates an LLMClient from the current application settings.
This is the single construction point for production LLM providers.
"""

from forgeai.config.settings import settings
from forgeai.llm.client import LLMClient
from forgeai.llm.errors import LLMConfigurationError


def create_llm_client() -> LLMClient:
    """Construct an LLMClient from the application settings.

    Returns:
        A configured LLMClient backed by the OmniRoute provider.

    Raises:
        LLMConfigurationError: If no LLM provider is configured
            (i.e. FORGEAI_OMNIROUTE_BASE_URL is unset).
    """
    if settings.omniroute_base_url:
        # Import here to avoid pulling httpx into tests that don't need it.
        from forgeai.llm.providers.omniroute import OmniRouteAdapter

        return OmniRouteAdapter()

    raise LLMConfigurationError(
        "No LLM provider is configured. "
        "Set FORGEAI_OMNIROUTE_BASE_URL (and optionally FORGEAI_OMNIROUTE_API_KEY) "
        "in your environment or .env file."
    )
