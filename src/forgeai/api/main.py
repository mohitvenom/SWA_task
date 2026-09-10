"""ForgeAI HTTP API."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from forgeai.agents.models import ExecutionResult, ExecutionStatus
from forgeai.api.workspace import WorkspaceAuthorizationError, validate_workspace
from forgeai.config.settings import settings
from forgeai.git.service import GitCLIWorkspaceService
from forgeai.llm.errors import LLMConfigurationError
from forgeai.llm.factory import create_llm_client
from forgeai.orchestrator import ApplicationOrchestrator
from forgeai.tools.registry import ToolRegistry

logger = logging.getLogger("forgeai.api")

app = FastAPI(
    title="ForgeAI API",
    description="API for the ForgeAI autonomous software engineering agent.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str
    version: str


class ExecuteRequest(BaseModel):
    """Request body for the /execute endpoint.

    Both fields are validated at the API boundary before any execution begins.
    """

    task: str = Field(
        description="Natural-language description of the software engineering task.",
        min_length=1,
    )
    workspace_root: str = Field(
        description="Absolute path to the Git workspace root on the server filesystem.",
        min_length=1,
    )

    @field_validator("task")
    @classmethod
    def validate_task(cls, v: str) -> str:
        """Reject empty, oversized, or injection-bearing task strings."""
        if "\x00" in v:
            raise ValueError("task must not contain null bytes")
        max_len = settings.api_task_max_length
        if len(v) > max_len:
            raise ValueError(f"task exceeds maximum length of {max_len} characters")
        stripped = v.strip()
        if not stripped:
            raise ValueError("task must not be blank")
        return v

    @field_validator("workspace_root")
    @classmethod
    def validate_workspace_root_field(cls, v: str) -> str:
        """Structural pre-check: reject null bytes in workspace_root before path parsing."""
        if "\x00" in v:
            raise ValueError("workspace_root must not contain null bytes")
        if not v.strip():
            raise ValueError("workspace_root must not be blank")
        return v


# Map terminal statuses to HTTP status codes.
_STATUS_HTTP: dict[ExecutionStatus, int] = {
    ExecutionStatus.COMPLETED: 200,
    ExecutionStatus.NEEDS_CLARIFICATION: 422,
    ExecutionStatus.SECURITY_REJECTED: 403,
    ExecutionStatus.FAILED: 500,
    ExecutionStatus.ROLLED_BACK: 500,
}

# Generic safe message for unexpected internal errors — never leak specifics.
_INTERNAL_ERROR_MSG = (
    "An internal error occurred. Check server logs for details."
)


def _build_orchestrator(resolved_workspace: Path) -> ApplicationOrchestrator:
    """Construct an ApplicationOrchestrator from settings.

    Args:
        resolved_workspace: Already-validated, canonically resolved workspace path.

    Raises:
        HTTPException(503): If the LLM provider is not configured.
    """
    try:
        llm = create_llm_client()
    except LLMConfigurationError as exc:
        logger.error("LLM provider not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    git = GitCLIWorkspaceService(resolved_workspace)
    registry = ToolRegistry()
    return ApplicationOrchestrator(llm, registry, git)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/execute")
async def execute_task(body: ExecuteRequest) -> JSONResponse:
    """Execute an autonomous software engineering task.

    The workspace_root is validated before any LLM or agent is activated.
    Internal exceptions never propagate details to the caller.

    HTTP status codes:

    - 200 COMPLETED
    - 400 Invalid/unauthorized workspace or malformed request
    - 403 SECURITY_REJECTED
    - 422 NEEDS_CLARIFICATION (or Pydantic validation error)
    - 500 FAILED / ROLLED_BACK / unexpected error
    - 503 LLM provider not configured
    """
    # --- Workspace authorization (before LLM construction) ---
    try:
        resolved_workspace = validate_workspace(body.workspace_root)
    except WorkspaceAuthorizationError as exc:
        logger.warning("Workspace authorization failed: %s", exc.detail or exc.reason)
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    # --- Orchestrator construction ---
    orchestrator = _build_orchestrator(resolved_workspace)

    logger.info(
        "POST /execute — task=%r workspace=%s",
        body.task[:80],
        resolved_workspace,
    )

    # --- Execution with safe error boundary ---
    try:
        result: ExecutionResult = await orchestrator.execute_task(
            body.task, resolved_workspace
        )
    except Exception as exc:
        # Unexpected exception escaped the orchestrator — do not expose details.
        logger.exception("Unexpected error in execute_task: %s", exc)
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR_MSG) from exc

    http_status = _STATUS_HTTP.get(result.status, 500)
    return JSONResponse(
        status_code=http_status,
        content=result.model_dump(mode="json"),
    )
