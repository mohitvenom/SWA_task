"""
ForgeAI Application Orchestrator.

Unifies the agent lifecycle across all phases.
"""

import uuid
from pathlib import Path
from typing import Any

import anyio

from forgeai.agents.coder import CodingAgent
from forgeai.agents.environment_intelligence import DependencyDiscovery, EnvironmentIntelligenceAgent
from forgeai.agents.failure_diagnosis import FailureDiagnosisAgent
from forgeai.agents.models import (
    AgentTask,
    CodingPhase,
    EngineeringPlan,
    EngineeringTask,
    ExecutionResult,
    ExecutionStatus,
    TaskIntelligenceStatus,
    TestStrategy,
)
from forgeai.agents.planner import PlanningAgent
from forgeai.agents.reviewer import ReviewAgent
from forgeai.agents.task_intelligence import TaskIntelligenceAgent
from forgeai.agents.test_strategy import TestStrategyAgent
from forgeai.config.settings import settings
from forgeai.git.interface import GitService
from forgeai.git.models import WorkspaceCheckpoint
from forgeai.llm.client import LLMClient
from forgeai.memory.builder import MemoryContextBuilder
from forgeai.memory.models import ExecutionEvent, ExecutionRecord
from forgeai.memory.store import SQLiteMemoryStore
from forgeai.repository.scanner import RepositoryScanner
from forgeai.tools.errors import SecurityViolationError
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
        try:
            event = ExecutionEvent(
                execution_id=execution_id,
                phase=phase,
                event_type=event_type,
                summary=content,
                metadata={"category": category} if category else {},
            )
            self.memory_store.save_event(event)
        except Exception:
            pass

    async def execute_task(self, raw_request: str, workspace_root: Path) -> ExecutionResult:
        """Execute the full autonomous software engineering lifecycle."""
        task_id = str(uuid.uuid4())
        execution_id = str(uuid.uuid4())

        if not settings.autonomous_execution_enabled:
            return ExecutionResult(
                execution_id=execution_id,
                task_id=task_id,
                status=ExecutionStatus.SECURITY_REJECTED,
                summary="Autonomous execution disabled by configuration",
            )
        
        # Get repository identity
        try:
            repo_identity = workspace_root.name
            status = await self.git.get_status()
            repo_revision = str(status.is_clean)
        except Exception:
            repo_identity = "unknown"
            repo_revision = "unknown"

        if settings.memory_enabled:
            try:
                record = ExecutionRecord(
                    execution_id=execution_id,
                    task_id=task_id,
                    repository_identifier=repo_identity,
                    repository_revision=repo_revision,
                    task_summary=raw_request,
                )
                self.memory_store.save_execution(record)
            except Exception:
                pass

        # Build context
        try:
            memory_context = self.context_builder.build_context(repo_identity, task_id)
        except Exception:
            memory_context = None

        checkpoint_created = False
        mutation_started = False
        commit_completed = False
        branch_name: str | None = None
        checkpoint_hash: str | None = None

        try:
            with anyio.fail_after(settings.max_execution_duration):
                # 1. Task Intelligence
                await self._log_event(execution_id, "TASK_INTELLIGENCE", "START", "Starting task intelligence")
                task_agent = TaskIntelligenceAgent(self.llm)
                eng_task = await task_agent.analyze(raw_request, memory_context=memory_context)
                await self._log_event(execution_id, "TASK_INTELLIGENCE", "SUCCESS", "Parsed engineering task")

                if eng_task.status in (TaskIntelligenceStatus.NEEDS_CLARIFICATION, TaskIntelligenceStatus.REJECTED):
                    await self._log_event(execution_id, "TASK_INTELLIGENCE", "TERMINATED", "Needs clarification")
                    return ExecutionResult(
                        execution_id=execution_id,
                        task_id=task_id,
                        status=ExecutionStatus.NEEDS_CLARIFICATION,
                        summary=f"Task intelligence returned {eng_task.status.value}",
                    )

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

                # Git Transaction
                await self._log_event(execution_id, "GIT_TRANSACTION", "START", "Initiating Git transaction")
                status = await self.git.get_status()
                if not status.is_clean:
                    raise SecurityViolationError("Workspace must be completely clean before coding.")
                
                branch = await self.git.create_branch(f"forgeai/task/{task_id}")
                branch_name = branch.name
                checkpoint = await self.git.create_checkpoint(task_id)
                checkpoint_hash = checkpoint.commit_hash
                checkpoint_created = True

                # 5. Coding & Validation & Repair
                mutation_started = True
                await self._log_event(execution_id, "CODING", "START", "Executing coding iterations")
                failure_agent = FailureDiagnosisAgent(self.llm)
                review_agent = ReviewAgent(self.llm, self.tools)
                coding_agent = CodingAgent(
                    self.llm, self.tools, self.git, review_agent, failure_agent
                )
                
                coding_result = await coding_agent.run(
                    eng_task, plan, workspace_root, strategy, memory_context=memory_context,
                    branch_name=branch_name, checkpoint_hash=checkpoint_hash
                )
                
                commit_completed = coding_result.committed

                if coding_result.success and coding_result.final_phase.value == "COMPLETED":
                    await self._log_event(execution_id, "CODING", "SUCCESS", "Coding task completed")
                    return ExecutionResult(
                        execution_id=execution_id,
                        task_id=task_id,
                        status=ExecutionStatus.COMPLETED,
                        summary=coding_result.summary,
                        changed_files=coding_result.changed_files,
                        validation_results=coding_result.validation_results,
                        review_result=coding_result.review_result,
                        repair_count=coding_result.session.repair_count,
                        git_result={"commit_hash": coding_result.commit_hash} if commit_completed else None,
                    )
                else:
                    await self._log_event(execution_id, "CODING", "FAILURE", f"Coding task failed: {coding_result.error_message}")
                    # Trigger rollback manually since Orchestrator owns the rollback
                    if checkpoint_created and not commit_completed:
                        await self.git.restore_checkpoint(WorkspaceCheckpoint(
                            task_id=task_id,
                            commit_hash=checkpoint_hash,
                            branch=branch_name,
                            status=await self.git.get_status()
                        ))
                    return ExecutionResult(
                        execution_id=execution_id,
                        task_id=task_id,
                        status=ExecutionStatus.FAILED,
                        summary=coding_result.summary,
                        failure_information=coding_result.error_message,
                        changed_files=coding_result.changed_files,
                        validation_results=coding_result.validation_results,
                        repair_count=coding_result.session.repair_count,
                    )

        except BaseException as e:
            # Handle cancellation, timeouts, and errors state-awarely
            is_cancellation = isinstance(e, (anyio.get_cancelled_exc_class(), TimeoutError))
            is_security = isinstance(e, SecurityViolationError)
            
            terminal_status = ExecutionStatus.SECURITY_REJECTED if is_security else ExecutionStatus.FAILED
            
            error_msg = str(e)
            if isinstance(e, TimeoutError):
                error_msg = "Execution timed out"
            elif is_cancellation:
                error_msg = "Execution was cancelled"
            
            await self._log_event(execution_id, "ORCHESTRATOR", "TERMINATED", error_msg, category="SYSTEM")
            
            # Rollback only if we have a checkpoint and didn't successfully commit
            if checkpoint_created and not commit_completed:
                try:
                    await self.git.restore_checkpoint(WorkspaceCheckpoint(
                        task_id=task_id,
                        commit_hash=checkpoint_hash, # type: ignore
                        branch=branch_name, # type: ignore
                        status=await self.git.get_status()
                    ))
                    if not is_security:
                        terminal_status = ExecutionStatus.ROLLED_BACK
                except Exception as rollback_e:
                    error_msg += f" | Rollback failed: {rollback_e}"
            
            # Record failed execution state
            result = ExecutionResult(
                execution_id=execution_id,
                task_id=task_id,
                status=terminal_status,
                summary=error_msg,
                failure_information=error_msg,
            )
            
            if isinstance(e, anyio.get_cancelled_exc_class()):
                raise e
            
            return result
