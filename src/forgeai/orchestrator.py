"""
ForgeAI Application Orchestrator.

Unifies the agent lifecycle across all phases.
"""

import uuid
from pathlib import Path
from typing import Any

from forgeai.agents.coder import CodingAgent
from forgeai.agents.environment_intelligence import DependencyDiscovery, EnvironmentIntelligenceAgent
from forgeai.agents.failure_diagnosis import FailureDiagnosisAgent
from forgeai.agents.models import (
    AgentTask,
    EngineeringPlan,
    EngineeringTask,
    TestStrategy,
)
from forgeai.agents.planner import PlanningAgent
from forgeai.agents.reviewer import ReviewAgent
from forgeai.agents.task_intelligence import TaskIntelligenceAgent
from forgeai.agents.test_strategy import TestStrategyAgent
from forgeai.config.settings import settings
from forgeai.git.interface import GitService
from forgeai.llm.client import LLMClient
from forgeai.memory.builder import MemoryContextBuilder
from forgeai.memory.models import ExecutionEvent, ExecutionRecord
from forgeai.memory.store import SQLiteMemoryStore
from forgeai.repository.scanner import RepositoryScanner
from forgeai.tools.registry import ToolRegistry


class ApplicationOrchestrator:
    """Coordinates the ForgeAI lifecycle and manages execution history."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        git_service: GitService,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.git = git_service
        self.memory_store = SQLiteMemoryStore(db_path=Path(settings.memory_db_path))
        self.context_builder = MemoryContextBuilder(self.memory_store)

    async def _log_event(self, execution_id: str, phase: str, event_type: str, content: str, category: str | None = None) -> None:
        """Helper to log execution events idempotently if memory is enabled."""
        if not settings.memory_enabled:
            return
        event = ExecutionEvent(
            execution_id=execution_id,
            phase=phase,
            event_type=event_type,
            summary=content,
            metadata={"category": category} if category else {},
        )
        self.memory_store.save_event(event)

    async def execute_task(self, raw_request: str, workspace_root: Path) -> dict[str, Any]:
        """Execute the full autonomous software engineering lifecycle."""
        task_id = str(uuid.uuid4())
        execution_id = str(uuid.uuid4())
        
        # Get repository identity
        try:
            repo_identity = workspace_root.name
            repo_revision = str((await self.git.get_status()).is_clean)
        except Exception:
            repo_identity = "unknown"
            repo_revision = "unknown"

        if settings.memory_enabled:
            record = ExecutionRecord(
                execution_id=execution_id,
                task_id=task_id,
                repository_identifier=repo_identity,
                repository_revision=repo_revision,
                task_summary=raw_request,
            )
            self.memory_store.save_execution(record)

        # Build context
        memory_context = self.context_builder.build_context(repo_identity, task_id)

        try:
            # 1. Task Intelligence
            await self._log_event(execution_id, "TASK_INTELLIGENCE", "START", "Starting task intelligence")
            task_agent = TaskIntelligenceAgent(self.llm)
            eng_task = await task_agent.analyze(raw_request, memory_context=memory_context)
            await self._log_event(execution_id, "TASK_INTELLIGENCE", "SUCCESS", "Parsed engineering task")

            # 2. Repository & Environment Intelligence
            await self._log_event(execution_id, "REPOSITORY_INTELLIGENCE", "START", "Analyzing repository")
            repo_scanner = RepositoryScanner(workspace_root)
            snapshot = repo_scanner.scan()
            
            dep_discovery = DependencyDiscovery(workspace_root)
            dep_snap, env_snap = dep_discovery.discover()
            env_agent = EnvironmentIntelligenceAgent(self.llm)
            env_diagnosis = env_agent.analyze(dep_snap, env_snap, memory_context=memory_context)
            await self._log_event(execution_id, "REPOSITORY_INTELLIGENCE", "SUCCESS", "Snapshot created")

            # 3. Planning
            await self._log_event(execution_id, "PLANNING", "START", "Generating plan")
            planning_agent = PlanningAgent(self.llm)
            plan = await planning_agent.plan(eng_task, snapshot, memory_context=memory_context)
            await self._log_event(execution_id, "PLANNING", "SUCCESS", "Plan authorized")

            # 4. Test Strategy
            await self._log_event(execution_id, "TEST_STRATEGY", "START", "Designing test strategy")
            strategy_agent = TestStrategyAgent(self.llm)
            strategy = await strategy_agent.generate_strategy(eng_task, plan, snapshot, memory_context=memory_context)
            await self._log_event(execution_id, "TEST_STRATEGY", "SUCCESS", "Test strategy generated")

            # 5. Coding & Validation & Repair
            await self._log_event(execution_id, "CODING", "START", "Executing coding iterations")
            failure_agent = FailureDiagnosisAgent(self.llm)
            review_agent = ReviewAgent(self.llm, self.tools)
            coding_agent = CodingAgent(
                self.llm, self.tools, self.git, review_agent, failure_agent
            )
            
            agent_task = AgentTask(task_id=task_id, description=raw_request)
            coding_result = await coding_agent.run(
                agent_task, plan, workspace_root, strategy, memory_context=memory_context
            )
            
            if coding_result.success:
                await self._log_event(execution_id, "CODING", "SUCCESS", "Coding task completed")
            else:
                await self._log_event(execution_id, "CODING", "FAILURE", f"Coding task failed: {coding_result.error_message}")

            return {
                "task_id": task_id,
                "success": coding_result.success,
                "coding_result": coding_result,
            }

        except Exception as e:
            await self._log_event(execution_id, "ORCHESTRATOR", "ERROR", str(e), category="SYSTEM")
            return {
                "task_id": task_id,
                "success": False,
                "error": str(e),
            }
