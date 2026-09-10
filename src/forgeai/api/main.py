"""ForgeAI HTTP API."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from forgeai.agents.models import ExecutionResult, ExecutionStatus
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
    """Request body for the /execute endpoint."""

    task: str
    """Natural-language description of the software engineering task."""

    workspace_root: str
    """Absolute path to the Git workspace root on the server filesystem."""


# Map terminal statuses to HTTP status codes.
_STATUS_HTTP: dict[ExecutionStatus, int] = {
    ExecutionStatus.COMPLETED: 200,
    ExecutionStatus.NEEDS_CLARIFICATION: 422,
    ExecutionStatus.SECURITY_REJECTED: 403,
    ExecutionStatus.FAILED: 500,
    ExecutionStatus.ROLLED_BACK: 500,
}


def _build_orchestrator(workspace_root: Path) -> ApplicationOrchestrator:
    """Construct an ApplicationOrchestrator from settings.

    Raises:
        HTTPException(503): If the LLM provider is not configured.
        HTTPException(400): If the workspace path does not exist.
    """
    if not workspace_root.exists() or not workspace_root.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"workspace_root does not exist or is not a directory: {workspace_root}",
        )

    try:
        llm = create_llm_client()
    except LLMConfigurationError as exc:
        logger.error("LLM provider not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    git = GitCLIWorkspaceService(workspace_root)
    registry = ToolRegistry()
    return ApplicationOrchestrator(llm, registry, git)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/execute")
async def execute_task(body: ExecuteRequest) -> JSONResponse:
    """Execute an autonomous software engineering task.

    Returns a structured ExecutionResult. The HTTP status code reflects the
    terminal execution status:

    - 200 COMPLETED
    - 422 NEEDS_CLARIFICATION
    - 403 SECURITY_REJECTED
    - 500 FAILED / ROLLED_BACK
    """
    workspace_root = Path(body.workspace_root)
    orchestrator = _build_orchestrator(workspace_root)

    logger.info("POST /execute — task=%r workspace=%s", body.task[:80], workspace_root)

    result: ExecutionResult = await orchestrator.execute_task(body.task, workspace_root)

    http_status = _STATUS_HTTP.get(result.status, 500)
    return JSONResponse(
        status_code=http_status,
        content=result.model_dump(mode="json"),
    )
