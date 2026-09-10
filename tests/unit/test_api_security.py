"""
Phase 23 — API & Workspace Security Hardening Tests.

Covers the new security boundary added to the /execute endpoint:

- workspace traversal sequences rejected before LLM activation
- workspace outside authorized allowlist rejected
- nonexistent workspace rejected
- workspace is a file (not a directory) rejected
- relative path rejected
- system-critical root rejected
- null bytes in workspace_root rejected
- null bytes in task rejected
- oversized task rejected
- blank task rejected
- internal exception → safe generic 500 (no path/stack leak)
- security rejection (SECURITY_REJECTED) before LLM activation
- valid authorized workspace continues to execute normally
- execution timeout setting is respected (not a new limit)
- WorkspaceAuthorizationError carries safe reason and detail
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from forgeai.agents.models import ExecutionResult, ExecutionStatus
from forgeai.api.workspace import WorkspaceAuthorizationError, validate_workspace
from forgeai.config.settings import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    from forgeai.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, task: str, workspace: str) -> dict:  # type: ignore[type-arg]
    resp = client.post("/execute", json={"task": task, "workspace_root": workspace})
    return {"status_code": resp.status_code, "body": resp.json()}


def _make_result(status: ExecutionStatus) -> ExecutionResult:
    return ExecutionResult(
        execution_id="eid",
        task_id="tid",
        status=status,
        summary="test",
        duration=0.1,
    )


# ---------------------------------------------------------------------------
# validate_workspace() unit tests — pure function, no HTTP
# ---------------------------------------------------------------------------


class TestValidateWorkspace:
    """validate_workspace rejects unsafe inputs before any orchestrator code runs."""

    def test_accepts_valid_directory(self, tmp_path: Path) -> None:
        result = validate_workspace(str(tmp_path))
        assert result.is_absolute()
        assert result.is_dir()

    def test_rejects_traversal_dotdot(self) -> None:
        with pytest.raises(WorkspaceAuthorizationError, match="disallowed path sequences"):
            validate_workspace("/tmp/../etc")

    def test_rejects_double_slash(self) -> None:
        with pytest.raises(WorkspaceAuthorizationError, match="disallowed path sequences"):
            validate_workspace("//etc/passwd")

    def test_rejects_null_byte(self) -> None:
        with pytest.raises(WorkspaceAuthorizationError, match="disallowed path sequences"):
            validate_workspace("/tmp/repo\x00evil")

    def test_rejects_url_encoded_traversal(self) -> None:
        with pytest.raises(WorkspaceAuthorizationError, match="disallowed path sequences"):
            validate_workspace("/tmp/%2e%2e/etc")

    def test_rejects_relative_path(self) -> None:
        with pytest.raises(WorkspaceAuthorizationError, match="absolute"):
            validate_workspace("relative/path/to/repo")

    def test_rejects_nonexistent_path(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "definitely_does_not_exist_xyzzy"
        with pytest.raises(WorkspaceAuthorizationError, match="does not exist"):
            validate_workspace(str(nonexistent))

    def test_rejects_file_not_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "somefile.txt"
        f.write_text("data")
        with pytest.raises(WorkspaceAuthorizationError, match="directory"):
            validate_workspace(str(f))

    def test_rejects_unix_root(self) -> None:
        # Only applicable on Unix; on Windows / is not a valid path anyway.
        import sys

        if sys.platform == "win32":
            pytest.skip("Unix-root test not applicable on Windows")
        with pytest.raises(WorkspaceAuthorizationError, match="system-critical"):
            validate_workspace("/")

    def test_allowlist_enforced_when_configured(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        original = settings.allowed_workspace_roots
        try:
            settings.allowed_workspace_roots = [str(allowed)]
            with pytest.raises(WorkspaceAuthorizationError, match="authorized"):
                validate_workspace(str(outside))
        finally:
            settings.allowed_workspace_roots = original

    def test_allowlist_allows_subdirectory(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        sub = allowed / "project"
        sub.mkdir()

        original = settings.allowed_workspace_roots
        try:
            settings.allowed_workspace_roots = [str(allowed)]
            result = validate_workspace(str(sub))
            assert result == sub.resolve()
        finally:
            settings.allowed_workspace_roots = original

    def test_empty_allowlist_is_unrestricted(self, tmp_path: Path) -> None:
        original = settings.allowed_workspace_roots
        try:
            settings.allowed_workspace_roots = []
            result = validate_workspace(str(tmp_path))
            assert result.is_dir()
        finally:
            settings.allowed_workspace_roots = original

    def test_resolves_symlinks(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")
        result = validate_workspace(str(link))
        assert result == real.resolve()


# ---------------------------------------------------------------------------
# WorkspaceAuthorizationError
# ---------------------------------------------------------------------------


class TestWorkspaceAuthorizationError:
    def test_reason_is_safe(self) -> None:
        exc = WorkspaceAuthorizationError("safe reason", detail="sensitive /internal/path")
        assert "/internal/path" not in exc.reason
        assert exc.reason == "safe reason"
        assert exc.detail == "sensitive /internal/path"

    def test_default_detail_equals_reason(self) -> None:
        exc = WorkspaceAuthorizationError("only reason")
        assert exc.detail == "only reason"


# ---------------------------------------------------------------------------
# /execute endpoint — request validation (Pydantic layer)
# ---------------------------------------------------------------------------


class TestExecuteRequestValidation:
    """Pydantic validators on ExecuteRequest reject malformed input at the boundary."""

    @pytest.fixture()
    def client(self) -> TestClient:
        return _client()

    def test_empty_task_rejected(self, client: TestClient) -> None:
        with tempfile.TemporaryDirectory() as d:
            r = _post(client, "", d)
        # FastAPI returns 422 for Pydantic validation failures
        assert r["status_code"] == 422

    def test_blank_task_rejected(self, client: TestClient) -> None:
        with tempfile.TemporaryDirectory() as d:
            r = _post(client, "   ", d)
        assert r["status_code"] == 422

    def test_null_byte_in_task_rejected(self, client: TestClient) -> None:
        with tempfile.TemporaryDirectory() as d:
            r = _post(client, "fix\x00 this", d)
        assert r["status_code"] == 422

    def test_oversized_task_rejected(self, client: TestClient) -> None:
        original = settings.api_task_max_length
        try:
            settings.api_task_max_length = 10
            with tempfile.TemporaryDirectory() as d:
                r = _post(client, "A" * 11, d)
            assert r["status_code"] == 422
        finally:
            settings.api_task_max_length = original

    def test_null_byte_in_workspace_rejected(self, client: TestClient) -> None:
        r = _post(client, "fix it", "/tmp/repo\x00evil")
        assert r["status_code"] == 422

    def test_blank_workspace_rejected(self, client: TestClient) -> None:
        r = _post(client, "fix it", "   ")
        assert r["status_code"] == 422


# ---------------------------------------------------------------------------
# /execute endpoint — workspace authorization (before LLM)
# ---------------------------------------------------------------------------


class TestExecuteWorkspaceAuthorization:
    """Workspace checks must reject before any LLM/orchestrator is constructed."""

    @pytest.fixture()
    def client(self) -> TestClient:
        return _client()

    def _assert_no_llm_constructed(self, client: TestClient, task: str, workspace: str) -> int:
        """Post and assert LLM factory was never called; return HTTP status."""
        with patch("forgeai.api.main.create_llm_client") as mock_llm:
            r = _post(client, task, workspace)
            mock_llm.assert_not_called()
        return r["status_code"]

    def test_traversal_rejected_before_llm(self, client: TestClient) -> None:
        code = self._assert_no_llm_constructed(client, "fix it", "/tmp/../etc")
        assert code == 400

    def test_nonexistent_workspace_rejected_before_llm(self, client: TestClient, tmp_path: Path) -> None:
        nonexistent = str(tmp_path / "does_not_exist_xyzzy")
        code = self._assert_no_llm_constructed(client, "fix it", nonexistent)
        assert code == 400

    def test_file_as_workspace_rejected_before_llm(self, client: TestClient) -> None:
        with tempfile.NamedTemporaryFile() as f:
            code = self._assert_no_llm_constructed(client, "fix it", f.name)
        assert code == 400

    def test_relative_workspace_rejected_before_llm(self, client: TestClient) -> None:
        code = self._assert_no_llm_constructed(client, "fix it", "relative/path")
        assert code == 400

    def test_workspace_outside_allowlist_rejected_before_llm(self, client: TestClient) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            original = settings.allowed_workspace_roots
            try:
                settings.allowed_workspace_roots = [allowed]
                code = self._assert_no_llm_constructed(client, "fix it", outside)
                assert code == 400
            finally:
                settings.allowed_workspace_roots = original

    def test_error_response_does_not_leak_internal_paths(self, client: TestClient) -> None:
        """The 400 error body must use only the safe 'reason', not internal details."""
        with patch(
            "forgeai.api.main.validate_workspace",
            side_effect=WorkspaceAuthorizationError(
                reason="workspace_root is not within an authorized location",
                detail="Resolved /sensitive/internal/path not in allowlist",
            ),
        ):
            r = client.post(
                "/execute",
                json={"task": "fix it", "workspace_root": "/tmp/whatever"},
                follow_redirects=False,
            )
        assert r.status_code == 400
        body = r.json()["detail"]
        assert "/sensitive/internal/path" not in body
        assert "workspace_root is not within an authorized location" in body


# ---------------------------------------------------------------------------
# /execute endpoint — error boundary
# ---------------------------------------------------------------------------


class TestExecuteErrorBoundary:
    """Unexpected internal exceptions must not leak details through the API."""

    @pytest.fixture()
    def client(self) -> TestClient:
        return _client()

    def test_unexpected_exception_returns_safe_500(self, client: TestClient) -> None:
        """If execute_task raises unexpectedly, the response is a generic 500."""
        with (
            patch("forgeai.api.main.validate_workspace") as mock_ws,
            patch("forgeai.api.main._build_orchestrator") as mock_build,
        ):
            mock_ws.return_value = Path(tempfile.mkdtemp())
            mock_orch = MagicMock()
            mock_orch.execute_task = AsyncMock(
                side_effect=RuntimeError("super secret internal path /etc/secret and stack")
            )
            mock_build.return_value = mock_orch

            r = client.post(
                "/execute",
                json={"task": "fix it", "workspace_root": "/tmp/fake"},
            )

        assert r.status_code == 500
        detail = r.json()["detail"]
        assert "/etc/secret" not in detail
        assert "stack" not in detail.lower() or "stack" in "Check server logs"
        assert "internal error" in detail.lower()

    def test_security_rejection_status_distinguishable(self) -> None:
        """SECURITY_REJECTED must map to 403, not 500, so callers can distinguish it."""
        client = _client()
        result = _make_result(ExecutionStatus.SECURITY_REJECTED)

        with (
            patch("forgeai.api.main.validate_workspace") as mock_ws,
            patch("forgeai.api.main._build_orchestrator") as mock_build,
        ):
            mock_ws.return_value = Path(tempfile.mkdtemp())
            mock_orch = MagicMock()

            async def _rej(*args, **kwargs):  # type: ignore[no-untyped-def]
                return result

            mock_orch.execute_task = _rej
            mock_build.return_value = mock_orch

            r = client.post(
                "/execute",
                json={"task": "fix it", "workspace_root": "/tmp/fake"},
            )

        assert r.status_code == 403
        assert r.json()["status"] == "SECURITY_REJECTED"


# ---------------------------------------------------------------------------
# /execute endpoint — valid workspace executes normally
# ---------------------------------------------------------------------------


class TestExecuteValidWorkspace:
    """A valid authorized workspace must not be rejected."""

    def test_valid_workspace_reaches_orchestrator(self) -> None:
        client = _client()
        result = _make_result(ExecutionStatus.COMPLETED)

        with tempfile.TemporaryDirectory() as d:
            with (
                patch("forgeai.api.main.create_llm_client") as mock_llm,
                patch("forgeai.api.main._build_orchestrator") as mock_build,
            ):
                mock_llm.return_value = MagicMock()
                mock_orch = MagicMock()

                async def _ok(*args, **kwargs):  # type: ignore[no-untyped-def]
                    return result

                mock_orch.execute_task = _ok
                mock_build.return_value = mock_orch

                r = client.post(
                    "/execute",
                    json={"task": "add a multiply function", "workspace_root": d},
                )

        assert r.status_code == 200
        assert r.json()["status"] == "COMPLETED"

    def test_execution_timeout_setting_is_unchanged(self) -> None:
        """No new timeout system — max_execution_duration comes from settings."""
        assert hasattr(settings, "max_execution_duration")
        assert isinstance(settings.max_execution_duration, int)
        assert settings.max_execution_duration > 0
