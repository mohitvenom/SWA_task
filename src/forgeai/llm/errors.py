"""Domain-specific exceptions for LLM interactions."""


class LLMError(Exception):
    """Base exception for all LLM errors."""

    pass


class LLMConfigurationError(LLMError):
    """Raised when the LLM provider is misconfigured (e.g. missing API key)."""

    pass


class LLMAuthenticationError(LLMError):
    """Raised when the LLM provider rejects authentication credentials."""

    pass


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider rate limits the request."""

    pass


class LLMTimeoutError(LLMError):
    """Raised when a request to the LLM provider times out."""

    pass


class LLMResponseError(LLMError):
    """Raised when the LLM provider returns an invalid or malformed response."""

    pass


class LLMProviderError(LLMError):
    """Raised when the LLM provider returns a general HTTP or internal error."""

    pass
