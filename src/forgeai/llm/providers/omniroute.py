"""OmniRoute LLM provider adapter using the OpenAI-compatible HTTP API."""

import json
from typing import Any

import httpx

from forgeai.config.settings import settings
from forgeai.llm.client import LLMClient
from forgeai.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from forgeai.llm.models import LLMRequest, LLMResponse, LLMUsage


class OmniRouteAdapter(LLMClient):
    """Adapter for interacting with OmniRoute's OpenAI-compatible API."""

    def __init__(self, timeout_seconds: float = 60.0) -> None:
        """
        Initialize the OmniRoute adapter.

        Args:
            timeout_seconds: Timeout for HTTP requests in seconds.
        """
        self.base_url = settings.omniroute_base_url
        self.api_key = settings.omniroute_api_key
        self.timeout = timeout_seconds

        if not self.base_url:
            raise LLMConfigurationError("FORGEAI_OMNIROUTE_BASE_URL is not configured.")

    def _get_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMAuthenticationError("FORGEAI_OMNIROUTE_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        headers = self._get_headers()
        base_url = self.base_url
        if not base_url:
            raise LLMConfigurationError("FORGEAI_OMNIROUTE_BASE_URL is not configured.")
        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [],
        }

        for msg in request.messages:
            msg_dict: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                msg_dict["content"] = msg.content
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            payload["messages"].append(msg_dict)

        if request.tools:
            payload["tools"] = request.tools

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Request to OmniRoute timed out: {e}") from e
        except httpx.RequestError as e:
            raise LLMProviderError(f"OmniRoute network error: {e}") from e

        if response.status_code == 401:
            raise LLMAuthenticationError("OmniRoute rejected the provided API key.")
        elif response.status_code == 429:
            raise LLMRateLimitError("OmniRoute rate limit exceeded.")
        elif response.status_code >= 400:
            raise LLMProviderError(
                f"OmniRoute returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise LLMResponseError(f"Failed to parse OmniRoute JSON: {e}") from e

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")

            usage_data = data.get("usage", {})
            usage = LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            request_id = response.headers.get("x-request-id") or data.get("id")

            from forgeai.llm.models import LLMToolCall

            tool_calls = None
            if "tool_calls" in choice["message"]:
                tool_calls = []
                for tc in choice["message"]["tool_calls"]:
                    if tc.get("type") == "function":
                        func = tc.get("function", {})
                        args = func.get("arguments", "{}")
                        try:
                            parsed_args = json.loads(args)
                        except json.JSONDecodeError:
                            parsed_args = {}

                        tool_calls.append(
                            LLMToolCall(
                                id=tc.get("id", ""),
                                name=func.get("name", ""),
                                arguments=parsed_args,
                            )
                        )

            return LLMResponse(
                content=content,
                model=request.model,
                usage=usage,
                finish_reason=finish_reason,
                request_id=request_id,
                tool_calls=tool_calls,
            )
        except (KeyError, IndexError) as e:
            raise LLMResponseError(
                f"OmniRoute response is missing expected fields: {e}"
            ) from e
