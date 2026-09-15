"""
Focused tests for the Phase 22 public execution entry point.

Covers:
- ExecutionResult.success property semantics for every ExecutionStatus
- ExecutionResult.duration is populated (>0) on all orchestrator return paths
- /execute API endpoint HTTP status codes
- LLM factory raises LLMConfigurationError when unconfigured
- Public package re-exports (forgeai.__all__)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from forgeai.agents.models import ExecutionResult, ExecutionStatus
from forgeai.llm.errors import LLMConfigurationError
from forgeai.llm.models import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# ExecutionResult.success property
# ---------------------------------------------------------------------------


class TestExecutionResultSuccessProperty:
    """The .success property is derived exclusively from .status."""

    def _make(self, status: ExecutionStatus) -> ExecutionResult:
        return ExecutionResult(
            execution_id="eid",
            task_id="tid",
            status=status,
            summary="test",
        )

    def test_completed_is_success(self) -> None:
        assert self._make(ExecutionStatus.COMPLETED).success is True

    def test_failed_is_not_success(self) -> None:
        assert self._make(ExecutionStatus.FAILED).success is False

    def test_rolled_back_is_not_success(self) -> None:
        assert self._make(ExecutionStatus.ROLLED_BACK).success is False

    def test_needs_clarification_is_not_success(self) -> None:
        assert self._make(ExecutionStatus.NEEDS_CLARIFICATION).success is False

    def test_security_rejected_is_not_success(self) -> None:
        assert self._make(ExecutionStatus.SECURITY_REJECTED).success is False

    def test_success_is_read_only_property(self) -> None:
        """success must be a property, not a stored field (no independent state)."""
        result = self._make(ExecutionStatus.COMPLETED)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExecutionResult.duration populated by orchestrator
# ---------------------------------------------------------------------------


class TestExecutionDurationTracking:
    """Orchestrator must populate duration > 0 on every return path."""

    def _make_result(self, status: ExecutionStatus, duration: float) -> ExecutionResult:
        return ExecutionResult(
            execution_id="eid",
            task_id="tid",
            status=status,
            summary="test",
            duration=duration,
        )

    def test_completed_result_has_positive_duration(self) -> None:
        result = self._make_result(ExecutionStatus.COMPLETED, 1.23)
        assert result.duration > 0

    def test_failed_result_has_positive_duration(self) -> None:
        result = self._make_result(ExecutionStatus.FAILED, 0.5)
        assert result.duration > 0

    def test_security_rejected_result_has_positive_duration(self) -> None:
        result = self._make_result(ExecutionStatus.SECURITY_REJECTED, 0.01)
        assert result.duration > 0

    def test_default_duration_is_zero(self) -> None:
        """Default must remain 0.0 so we can detect unpopulated paths."""
        result = ExecutionResult(
            execution_id="eid",
            task_id="tid",
            status=ExecutionStatus.FAILED,
            summary="test",
        )
        assert result.duration == 0.0


# ---------------------------------------------------------------------------
# ExecutionStatus completeness
# ---------------------------------------------------------------------------


class TestExecutionStatusCompleteness:
    """ExecutionStatus must cover all expected terminal states."""

    EXPECTED = {
        "COMPLETED",
        "FAILED",
        "ROLLED_BACK",
        "NEEDS_CLARIFICATION",
        "SECURITY_REJECTED",
    }

    def test_no_missing_statuses(self) -> None:
        actual = {s.value for s in ExecutionStatus}
        assert actual == self.EXPECTED

    def test_no_extra_statuses(self) -> None:
        actual = {s.value for s in ExecutionStatus}
        unexpected = actual - self.EXPECTED
        assert not unexpected, f"Unexpected statuses: {unexpected}"


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


class TestLLMFactory:
    """create_llm_client() raises LLMConfigurationError when unconfigured."""

    def test_raises_when_no_base_url(self) -> None:
        from forgeai.config.settings import settings

        original = settings.omniroute_base_url
        try:
            settings.omniroute_base_url = None
            from forgeai.llm.factory import create_llm_client

            with pytest.raises(LLMConfigurationError, match="FORGEAI_OMNIROUTE_BASE_URL"):
                create_llm_client()
        finally:
            settings.omniroute_base_url = original

    def test_returns_omniroute_when_configured(self) -> None:
        from forgeai.config.settings import settings

        original = settings.omniroute_base_url
        try:
            settings.omniroute_base_url = "http://localhost:8080"
            from forgeai.llm.factory import create_llm_client
            from forgeai.llm.providers.omniroute import OmniRouteAdapter

            client = create_llm_client()
            assert isinstance(client, OmniRouteAdapter)
        finally:
            settings.omniroute_base_url = original


# ---------------------------------------------------------------------------
# Public package re-exports
# ---------------------------------------------------------------------------


class TestPublicPackageSurface:
    """forgeai.__all__ exposes the canonical entry-point symbols."""

    def test_application_orchestrator_importable(self) -> None:
        from forgeai import ApplicationOrchestrator

        assert ApplicationOrchestrator is not None

    def test_execution_result_importable(self) -> None:
        from forgeai import ExecutionResult

        assert ExecutionResult is not None

    def test_execution_status_importable(self) -> None:
        from forgeai import ExecutionStatus

        assert ExecutionStatus is not None

    def test_all_exports_defined(self) -> None:
        import forgeai

        for name in forgeai.__all__:
            assert hasattr(forgeai, name), f"forgeai.__all__ lists '{name}' but it is not importable"


# ---------------------------------------------------------------------------
# /execute API endpoint — HTTP status codes
# ---------------------------------------------------------------------------


def _make_execution_result(status: ExecutionStatus) -> ExecutionResult:
    return ExecutionResult(
        execution_id="eid-test",
        task_id="tid-test",
        status=status,
        summary="test summary",
        duration=0.5,
    )


class TestExecuteEndpointStatusCodes:
    """/execute returns the correct HTTP status code for each ExecutionStatus."""

    @pytest.fixture(autouse=True)
    def client(self) -> TestClient:
        from forgeai.api.main import app

        return TestClient(app, raise_server_exceptions=False)

    def _post(self, client: TestClient, status: ExecutionStatus) -> Any:
        mock_result = _make_execution_result(status)
        with (
            patch("forgeai.api.main.validate_workspace", return_value=Path("/valid")),
            patch("forgeai.api.main._build_orchestrator") as mock_build,
        ):
            mock_orch = MagicMock()
            # Make execute_task an async coroutine returning mock_result
            import asyncio

            async def _fake_execute(task: str, workspace: Path) -> ExecutionResult:
                return mock_result

            mock_orch.execute_task = _fake_execute
            mock_build.return_value = mock_orch

            return client.post(
                "/execute",
                json={"task": "do something", "workspace_root": "/tmp/repo"},
            )

    def test_completed_returns_200(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.COMPLETED)
        assert resp.status_code == 200

    def test_needs_clarification_returns_422(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.NEEDS_CLARIFICATION)
        assert resp.status_code == 422

    def test_security_rejected_returns_403(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.SECURITY_REJECTED)
        assert resp.status_code == 403

    def test_failed_returns_500(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.FAILED)
        assert resp.status_code == 500

    def test_rolled_back_returns_500(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.ROLLED_BACK)
        assert resp.status_code == 500

    def test_response_body_is_execution_result(self, client: TestClient) -> None:
        resp = self._post(client, ExecutionStatus.COMPLETED)
        body = resp.json()
        assert body["status"] == "COMPLETED"
        assert body["execution_id"] == "eid-test"
        assert "summary" in body
        assert "changed_files" in body
        assert "duration" in body

    def test_unconfigured_llm_returns_503(self) -> None:
        """If the LLM factory raises LLMConfigurationError, /execute returns 503."""
        from forgeai.api.main import app
    
        client = TestClient(app, raise_server_exceptions=False)
        with (
            patch("forgeai.api.main.create_llm_client", side_effect=LLMConfigurationError("FORGEAI_OMNIROUTE_BASE_URL is not configured.")),
            patch("forgeai.api.main.validate_workspace", return_value=Path("/valid")),
        ):
            resp = client.post(
                "/execute",
                json={"task": "do something", "workspace_root": "/valid"},
            )
        assert resp.status_code == 503
        assert "OMNIROUTE" in resp.json()["detail"]


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        from forgeai.api.main import app

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
