"""
ForgeAI Application Orchestrator.

Unifies the agent lifecycle across all phases.
"""

import logging
import re
import time
import uuid
from pathlib import Path

import anyio

from forgeai.agents.coder import CodingAgent
from forgeai.agents.environment_intelligence import DependencyDiscovery, EnvironmentIntelligenceAgent
from forgeai.agents.failure_diagnosis import FailureDiagnosisAgent
from forgeai.agents.models import (
    EngineeringTask,
    ExecutionResult,
    ExecutionStatus,
    TaskIntelligenceStatus,
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

logger = logging.getLogger("forgeai.orchestrator")


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
        """Execute the full autonomous software engineering lifecycle.

        Args:
            raw_request: The user's natural-language task description.
            workspace_root: Absolute path to the Git workspace root.

        Returns:
            A structured ExecutionResult describing the terminal outcome.
            All expected failure modes are represented as non-COMPLETED statuses;
            internal exceptions never leak through this boundary.
        """
        task_id = str(uuid.uuid4())
        execution_id = str(uuid.uuid4())
        start_time = time.monotonic()

        logger.info("[%s] Starting execution: %r", execution_id, raw_request[:120])

        if not settings.autonomous_execution_enabled:
            logger.warning("[%s] Autonomous execution is disabled by configuration.", execution_id)
            return ExecutionResult(
                execution_id=execution_id,
                task_id=task_id,
                status=ExecutionStatus.SECURITY_REJECTED,
                summary="Autonomous execution disabled by configuration",
                duration=time.monotonic() - start_time,
            )

        fast_path_match = re.match(r"(?i)^create\s+(?:a\s+file\s+named\s+)?([^\s]+)\s+containing\s+exactly:\s*(.*)$", raw_request.strip())
        if fast_path_match:
            return await self._execute_fast_path(
                raw_request=raw_request,
                file_path=fast_path_match.group(1),
                content=fast_path_match.group(2),
                workspace_root=workspace_root,
                task_id=task_id,
                execution_id=execution_id,
                start_time=start_time,
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
                logger.info("[%s] Phase: TASK_INTELLIGENCE", execution_id)
                await self._log_event(execution_id, "TASK_INTELLIGENCE", "START", "Starting task intelligence")
                task_agent = TaskIntelligenceAgent(self.llm)
                eng_task = await task_agent.analyze(raw_request, memory_context=memory_context)
                await self._log_event(execution_id, "TASK_INTELLIGENCE", "SUCCESS", "Parsed engineering task")

                if eng_task.status in (TaskIntelligenceStatus.NEEDS_CLARIFICATION, TaskIntelligenceStatus.REJECTED):
                    logger.info("[%s] Task requires clarification (status=%s).", execution_id, eng_task.status.value)
                    await self._log_event(execution_id, "TASK_INTELLIGENCE", "TERMINATED", "Needs clarification")
                    return ExecutionResult(
                        execution_id=execution_id,
                        task_id=task_id,
                        status=ExecutionStatus.NEEDS_CLARIFICATION,
                        summary=f"Task intelligence returned {eng_task.status.value}",
                        duration=time.monotonic() - start_time,
                    )

                # 2. Repository & Environment Intelligence
                logger.info("[%s] Phase: REPOSITORY_INTELLIGENCE", execution_id)
                await self._log_event(execution_id, "REPOSITORY_INTELLIGENCE", "START", "Analyzing repository")
                repo_scanner = RepositoryScanner(workspace_root)
                snapshot = repo_scanner.scan()

                dep_discovery = DependencyDiscovery(workspace_root)
                dep_snap, env_snap = dep_discovery.discover()
                env_agent = EnvironmentIntelligenceAgent(self.llm)
                env_diagnosis = env_agent.analyze(dep_snap, env_snap, memory_context=memory_context)
                await self._log_event(execution_id, "REPOSITORY_INTELLIGENCE", "SUCCESS", "Snapshot created")

                # 3. Planning
                logger.info("[%s] Phase: PLANNING", execution_id)
                await self._log_event(execution_id, "PLANNING", "START", "Generating plan")
                planning_agent = PlanningAgent(self.llm)
                plan = await planning_agent.plan(eng_task, snapshot, memory_context=memory_context)
                await self._log_event(execution_id, "PLANNING", "SUCCESS", "Plan authorized")

                # 4. Test Strategy
                logger.info("[%s] Phase: TEST_STRATEGY", execution_id)
                await self._log_event(execution_id, "TEST_STRATEGY", "START", "Designing test strategy")
                strategy_agent = TestStrategyAgent(self.llm)
                strategy = await strategy_agent.generate_strategy(eng_task, plan, snapshot, memory_context=memory_context)
                await self._log_event(execution_id, "TEST_STRATEGY", "SUCCESS", "Test strategy generated")

                # Git Transaction
                logger.info("[%s] Phase: GIT_TRANSACTION — creating branch and checkpoint", execution_id)
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
                logger.info("[%s] Phase: CODING", execution_id)
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
                    elapsed = time.monotonic() - start_time
                    logger.info("[%s] Execution COMPLETED in %.1fs.", execution_id, elapsed)
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
                        duration=elapsed,
                    )
                else:
                    elapsed = time.monotonic() - start_time
                    logger.warning(
                        "[%s] Coding phase FAILED after %.1fs: %s",
                        execution_id, elapsed, coding_result.error_message,
                    )
                    await self._log_event(execution_id, "CODING", "FAILURE", f"Coding task failed: {coding_result.error_message}")
                    # Trigger rollback manually since Orchestrator owns the rollback
                    if checkpoint_created and not commit_completed:
                        await self.git.restore_checkpoint(WorkspaceCheckpoint(
                            task_id=task_id,
                            commit_hash=checkpoint_hash,  # type: ignore[arg-type]
                            branch=branch_name,  # type: ignore[arg-type]
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
                        duration=elapsed,
                    )

        except BaseException as e:
            elapsed = time.monotonic() - start_time
            # Handle cancellation, timeouts, and errors state-awarely
            is_cancellation = isinstance(e, (anyio.get_cancelled_exc_class(), TimeoutError))
            is_security = isinstance(e, SecurityViolationError)

            terminal_status = ExecutionStatus.SECURITY_REJECTED if is_security else ExecutionStatus.FAILED

            error_msg = str(e)
            if isinstance(e, TimeoutError):
                error_msg = "Execution timed out"
            elif is_cancellation:
                error_msg = "Execution was cancelled"

            logger.warning(
                "[%s] Execution terminated after %.1fs (%s): %s",
                execution_id, elapsed, terminal_status.value, error_msg,
            )
            await self._log_event(execution_id, "ORCHESTRATOR", "TERMINATED", error_msg, category="SYSTEM")

            # Rollback only if we have a checkpoint and didn't successfully commit
            if checkpoint_created and not commit_completed:
                try:
                    await self.git.restore_checkpoint(WorkspaceCheckpoint(
                        task_id=task_id,
                        commit_hash=checkpoint_hash,  # type: ignore[arg-type]
                        branch=branch_name,  # type: ignore[arg-type]
                        status=await self.git.get_status()
                    ))
                    if not is_security:
                        terminal_status = ExecutionStatus.ROLLED_BACK
                    logger.info("[%s] Rollback completed.", execution_id)
                except Exception as rollback_e:
                    error_msg += f" | Rollback failed: {rollback_e}"
                    logger.error("[%s] Rollback failed: %s", execution_id, rollback_e)

            result = ExecutionResult(
                execution_id=execution_id,
                task_id=task_id,
                status=terminal_status,
                summary=error_msg,
                failure_information=error_msg,
                duration=elapsed,
            )

            if isinstance(e, anyio.get_cancelled_exc_class()):
                raise e

            return result

    async def _execute_fast_path(
        self,
        raw_request: str,
        file_path: str,
        content: str,
        workspace_root: Path,
        task_id: str,
        execution_id: str,
        start_time: float,
    ) -> ExecutionResult:
        logger.info("[%s] Phase: FAST_PATH_EXECUTION", execution_id)
        await self._log_event(execution_id, "FAST_PATH", "START", "Executing simple task via fast path")

        checkpoint_created = False
        commit_completed = False
        branch_name: str | None = None
        checkpoint_hash: str | None = None

        try:
            with anyio.fail_after(settings.max_execution_duration):
                status = await self.git.get_status()
                if not status.is_clean:
                    raise SecurityViolationError("Workspace must be completely clean before coding.")

                branch = await self.git.create_branch(f"forgeai/task/{task_id}")
                branch_name = branch.name
                checkpoint = await self.git.create_checkpoint(task_id)
                checkpoint_hash = checkpoint.commit_hash
                checkpoint_created = True

                from forgeai.tools.models import ToolCall, ToolContext
                from forgeai.tools.errors import ToolRegistrationError

                try:
                    write_tool = self.tools.get("write_file")
                except ToolRegistrationError:
                    from forgeai.tools.repository.write_file import WriteFileTool
                    write_tool = WriteFileTool()
                    self.tools.register(write_tool)

                context = ToolContext(workspace_root=workspace_root, session_id=execution_id)
                call = ToolCall(call_id=str(uuid.uuid4()), name="write_file", arguments={"path": file_path, "content": content, "overwrite": True})
                result = await write_tool.execute(call, context)
                
                if not result.success:
                    raise Exception(f"Failed to write file: {result.error}")

                await self.git.stage_files([file_path])
                commit_obj = await self.git.commit(
                    message=f"Agent completed task {task_id} (Fast Path)", paths=[file_path]
                )
                commit_completed = True

                elapsed = time.monotonic() - start_time
                await self._log_event(execution_id, "FAST_PATH", "SUCCESS", "Fast path completed successfully")
                return ExecutionResult(
                    execution_id=execution_id,
                    task_id=task_id,
                    status=ExecutionStatus.COMPLETED,
                    summary="Fast path completed successfully.",
                    changed_files=[file_path],
                    validation_results=[],
                    review_result=None,
                    repair_count=0,
                    git_result={"commit_hash": commit_obj.commit_hash},
                    duration=elapsed,
                )
        except BaseException as e:
            elapsed = time.monotonic() - start_time
            is_cancellation = isinstance(e, (anyio.get_cancelled_exc_class(), TimeoutError))
            is_security = isinstance(e, SecurityViolationError)

            terminal_status = ExecutionStatus.SECURITY_REJECTED if is_security else ExecutionStatus.FAILED
            
            error_msg = str(e)
            if isinstance(e, TimeoutError):
                error_msg = "Execution timed out"
            elif is_cancellation:
                error_msg = "Execution was cancelled"
                
            logger.warning(
                "[%s] Fast path execution terminated after %.1fs (%s): %s",
                execution_id, elapsed, terminal_status.value, error_msg,
            )

            if checkpoint_created and not commit_completed and checkpoint_hash is not None:
                try:
                    await self.git.restore_checkpoint(WorkspaceCheckpoint(
                        task_id=task_id,
                        commit_hash=checkpoint_hash,  # type: ignore[arg-type]
                        branch=branch_name,  # type: ignore[arg-type]
                        status=await self.git.get_status()
                    ))
                    if not is_security:
                        terminal_status = ExecutionStatus.ROLLED_BACK
                except Exception as rollback_e:
                    error_msg += f" | Rollback failed: {rollback_e}"

            result = ExecutionResult(
                execution_id=execution_id,
                task_id=task_id,
                status=terminal_status,
                summary=error_msg,
                failure_information=error_msg,
                duration=elapsed,
            )

            if isinstance(e, anyio.get_cancelled_exc_class()):
                raise e

            return result
