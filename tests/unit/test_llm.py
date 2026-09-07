"""Tests for LLM abstractions and providers."""

import httpx
import pytest
import respx

from forgeai.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from forgeai.llm.models import LLMMessage, LLMRequest, LLMResponse, LLMUsage
from forgeai.llm.providers.mock import MockLLMProvider
from forgeai.llm.providers.omniroute import OmniRouteAdapter


@pytest.fixture
def mock_request() -> LLMRequest:
    return LLMRequest(
        model="test-model",
        messages=[LLMMessage(role="user", content="Hello")],
        temperature=0.7,
        max_tokens=100,
    )


def test_models_creation(mock_request: LLMRequest) -> None:
    """Test creating domain models."""
    assert mock_request.model == "test-model"
    assert mock_request.messages[0].role == "user"
    assert mock_request.messages[0].content == "Hello"

    usage = LLMUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15)
    assert usage.total_tokens == 15

    response = LLMResponse(content="Hi there", model="test-model", usage=usage)
    assert response.content == "Hi there"
    assert response.usage.prompt_tokens == 5


@pytest.mark.anyio
async def test_mock_provider_success(mock_request: LLMRequest) -> None:
    """Test MockLLMProvider successful generation."""
    provider = MockLLMProvider(default_response="Mocked response")
    response = await provider.generate(mock_request)

    assert response.content == "Mocked response"
    assert response.model == "test-model"
    assert response.usage.prompt_tokens == 10
    assert provider.call_count == 1
    assert provider.last_request == mock_request


@pytest.mark.anyio
async def test_mock_provider_factory(mock_request: LLMRequest) -> None:
    """Test MockLLMProvider with a custom response factory."""

    def factory(req: LLMRequest) -> LLMResponse:
        return LLMResponse(content=f"Echo {req.messages[0].content}", model=req.model)

    provider = MockLLMProvider(response_factory=factory)
    response = await provider.generate(mock_request)

    assert response.content == "Echo Hello"


@pytest.mark.anyio
async def test_mock_provider_failure(mock_request: LLMRequest) -> None:
    """Test MockLLMProvider simulating an error."""
    provider = MockLLMProvider(simulate_error=LLMRateLimitError("Too many requests"))
    with pytest.raises(LLMRateLimitError, match="Too many requests"):
        await provider.generate(mock_request)


def test_omniroute_adapter_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test OmniRouteAdapter raises LLMConfigurationError if base_url is missing."""
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": None, "omniroute_api_key": "fake"},
        )(),
    )
    with pytest.raises(
        LLMConfigurationError, match="FORGEAI_OMNIROUTE_BASE_URL is not configured"
    ):
        OmniRouteAdapter()


@pytest.mark.anyio
async def test_omniroute_adapter_missing_api_key(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    """Test OmniRouteAdapter raises LLMAuthenticationError if api_key is missing."""
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": None},
        )(),
    )

    adapter = OmniRouteAdapter()
    with pytest.raises(
        LLMAuthenticationError, match="FORGEAI_OMNIROUTE_API_KEY is not configured"
    ):
        await adapter.generate(mock_request)


@pytest.mark.anyio
@respx.mock
async def test_omniroute_adapter_success(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    """Test successful generation using OmniRouteAdapter."""
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": "fake-key"},
        )(),
    )

    respx.post("http://fake/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "test-req-123",
                "choices": [
                    {
                        "message": {
                            "content": "Success!",
                            "tool_calls": [
                                {
                                    "id": "tc-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_code",
                                        "arguments": '{"query": "def run"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )

    adapter = OmniRouteAdapter()
    response = await adapter.generate(mock_request)

    assert response.content == "Success!"
    assert response.finish_reason == "tool_calls"
    assert response.usage.total_tokens == 15
    assert response.request_id == "test-req-123"
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "tc-1"
    assert response.tool_calls[0].name == "search_code"
    assert response.tool_calls[0].arguments == {"query": "def run"}


@pytest.mark.anyio
@respx.mock
async def test_omniroute_adapter_auth_error(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": "fake-key"},
        )(),
    )
    respx.post("http://fake/v1/chat/completions").mock(return_value=httpx.Response(401))

    adapter = OmniRouteAdapter()
    with pytest.raises(LLMAuthenticationError):
        await adapter.generate(mock_request)


@pytest.mark.anyio
@respx.mock
async def test_omniroute_adapter_rate_limit(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": "fake-key"},
        )(),
    )
    respx.post("http://fake/v1/chat/completions").mock(return_value=httpx.Response(429))

    adapter = OmniRouteAdapter()
    with pytest.raises(LLMRateLimitError):
        await adapter.generate(mock_request)


@pytest.mark.anyio
@respx.mock
async def test_omniroute_adapter_timeout(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": "fake-key"},
        )(),
    )
    respx.post("http://fake/v1/chat/completions").mock(
        side_effect=httpx.TimeoutException("Timeout")
    )

    adapter = OmniRouteAdapter()
    with pytest.raises(LLMTimeoutError):
        await adapter.generate(mock_request)


@pytest.mark.anyio
@respx.mock
async def test_omniroute_adapter_malformed_response(
    monkeypatch: pytest.MonkeyPatch, mock_request: LLMRequest
) -> None:
    monkeypatch.setattr(
        "forgeai.llm.providers.omniroute.settings",
        type(
            "MockSettings",
            (),
            {"omniroute_base_url": "http://fake", "omniroute_api_key": "fake-key"},
        )(),
    )
    respx.post("http://fake/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"invalid": "data"})
    )

    adapter = OmniRouteAdapter()
    with pytest.raises(LLMResponseError):
        await adapter.generate(mock_request)
