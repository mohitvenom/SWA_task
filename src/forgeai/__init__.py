"""
ForgeAI — Autonomous Software Engineering Agent.

Public API surface. Import from here for stable, versioned symbols.

Example::

    import anyio
    from pathlib import Path
    from forgeai import ApplicationOrchestrator, ExecutionResult, ExecutionStatus
    from forgeai.llm.factory import create_llm_client
    from forgeai.git.service import GitCLIWorkspaceService
    from forgeai.tools.registry import ToolRegistry

    async def main() -> None:
        llm = create_llm_client()
        git = GitCLIWorkspaceService(Path("/path/to/repo"))
        registry = ToolRegistry()
        orchestrator = ApplicationOrchestrator(llm, registry, git)
        result = await orchestrator.execute_task("Add a multiply function", Path("/path/to/repo"))
        print(result.status, result.summary)

    anyio.run(main)
"""

from forgeai.agents.models import ExecutionResult, ExecutionStatus
from forgeai.orchestrator import ApplicationOrchestrator

__all__ = [
    "ApplicationOrchestrator",
    "ExecutionResult",
    "ExecutionStatus",
]
