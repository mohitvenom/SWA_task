"""Autonomous Coding Agent implementation."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from forgeai.agents.errors import AgentDecisionParseError, AgentMaxIterationsError
from forgeai.agents.models import (
    AgentTask,
    CodingDecision,
    CodingPhase,
    CodingResult,
    CodingSession,
    EngineeringPlan,
    ChangeSet,
    FileChange,
    ChangeOperation,
    ChangeSetStatus,
)
from forgeai.config.settings import settings
from forgeai.git.errors import GitError
from forgeai.git.interface import GitService
from forgeai.git.models import WorkspaceCheckpoint
from forgeai.llm.client import LLMClient
from forgeai.llm.errors import LLMError
from forgeai.llm.models import LLMMessage, LLMRequest, LLMToolCall
from forgeai.agents.reviewer import ReviewAgent
from forgeai.agents.models import ReviewStatus, ReviewResult, TestStrategy, DiagnosisStatus
from forgeai.agents.failure_diagnosis import FailureDiagnosisAgent
from forgeai.memory.models import MemoryContext
from forgeai.tools.errors import SecurityViolationError
from forgeai.tools.models import ToolCall, ToolCapability, ToolContext
from forgeai.tools.registry import ToolRegistry
from forgeai.tools.repository.utils import resolve_safe_path
from forgeai.policies.changeset import ChangeSetPolicy


class CodingPolicy:
    """Authorization policy for the Coding Agent."""

    @staticmethod
    def authorize_tool(
        tool_name: str,
        arguments: dict[str, Any],
        capability: ToolCapability,
        phase: CodingPhase,
        plan: EngineeringPlan,
        workspace_root: Path,
    ) -> None:
        """
        Validate if a tool is authorized for execution.

        Args:
            tool_name: The name of the tool.
            arguments: The arguments passed to the tool.
            capability: The capability of the tool.
            phase: The current coding phase.
            plan: The engineering plan context.
            workspace_root: The root of the workspace.

        Raises:
            SecurityViolationError: If unauthorized.
        """
        # Phase Authorization
        if phase == CodingPhase.INSPECTING:
            if capability != ToolCapability.READ_ONLY:
                raise SecurityViolationError(
                    f"Tool capability '{capability}' not allowed in INSPECTING phase."
                )
        elif phase == CodingPhase.IMPLEMENTING:
            if capability not in (ToolCapability.READ_ONLY, ToolCapability.MUTATION):
                raise SecurityViolationError(
                    f"Tool capability '{capability}' not allowed in IMPLEMENTING phase."
                )
        elif phase == CodingPhase.VALIDATING:
            if capability not in (ToolCapability.READ_ONLY, ToolCapability.EXECUTION):
                raise SecurityViolationError(
                    f"Tool capability '{capability}' not allowed in VALIDATING phase."
                )
        elif phase == CodingPhase.REPAIRING:
            # All capabilities allowed in repairing (inspect, mutate, execute)
            pass
        else:
            raise SecurityViolationError(
                f"Tool execution not allowed in phase: {phase}"
            )

        # Path Authorization for Mutation tools
        if capability == ToolCapability.MUTATION:
            target_file = (
                arguments.get("target_file")
                or arguments.get("file_path")
                or arguments.get("path")
            )
            if not target_file:
                # Some tools might use different argument names, but standard repository tools use target_file/file_path/path
                return

            resolved_target = resolve_safe_path(workspace_root, str(target_file))

            # Ensure it's not excluded
            for excl in plan.excluded_files:
                try:
                    excl_path = (workspace_root / excl).resolve()
                    if resolved_target == excl_path or resolved_target.is_relative_to(
                        excl_path
                    ):
                        raise SecurityViolationError(
                            f"Path '{target_file}' is explicitly excluded by the plan."
                        )
                except ValueError:
                    pass

            # Ensure it is in affected_files or authorized ChangeSet
            is_affected = False
            if plan.change_set and plan.change_set.status == ChangeSetStatus.AUTHORIZED:
                try:
                    norm_path = str(resolved_target.relative_to(workspace_root).as_posix())
                    if norm_path in plan.change_set.authorized_files:
                        is_affected = True
                except ValueError:
                    pass
            else:
                for aff in plan.affected_files:
                    try:
                        aff_path = (workspace_root / aff).resolve()
                        if resolved_target == aff_path or resolved_target.is_relative_to(
                            aff_path
                        ):
                            is_affected = True
                            break
                    except ValueError:
                        pass

            if not is_affected:
                raise SecurityViolationError(
                    f"Path '{target_file}' is not in the authorized ChangeSet/affected_files."
                )


class CodingAgent:
    """The autonomous coding agent that executes tasks bounded by policy."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        git_service: GitService,
        review_agent: ReviewAgent | None = None,
        failure_diagnosis_agent: FailureDiagnosisAgent | None = None,
    ) -> None:
        """
        Initialize the CodingAgent.

        Args:
            llm_client: The LLM client.
            tool_registry: The tool registry containing repository and execution tools.
            git_service: The Git service for workspace operations.
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.git_service = git_service
        self.review_agent = review_agent
        self.failure_diagnosis_agent = failure_diagnosis_agent

        self.max_iterations = settings.coding_max_iterations
        self.max_tool_calls = settings.coding_max_tool_calls
        self.max_repair_iterations = settings.coding_max_repair_iterations
        self.max_changed_files = settings.coding_max_changed_files
        self.max_output_size = settings.coding_max_validation_output

        self.messages: list[LLMMessage] = []

    def _get_system_prompt(self, plan: EngineeringPlan) -> str:
        schema = CodingDecision.model_json_schema()
        return (
            "You are an autonomous software engineering agent. You are operating "
            "inside a Git workspace and your goal is to implement an Engineering Plan. "
            "\n\nRules:\n"
            "1. You MUST inspect the relevant files before editing.\n"
            "2. Make minimal targeted changes.\n"
            "3. Do NOT modify files excluded by the plan.\n"
            "4. You must use tools to perform changes; do not just pretend to change them.\n"
            "5. Validate changes using validation tools when in the VALIDATING or REPAIRING phase.\n"
            "6. You must NOT output chain-of-thought. Provide concise, structured intent.\n"
            "7. When responding, you can either call tools OR output a JSON CodingDecision object.\n"
            "8. Once the task is fully complete, return a CodingDecision with `action`='finish' and `completion_requested`=true.\n\n"
            f"Engineering Plan:\n"
            f"- Objective: {plan.task_interpretation}\n"
            f"- Proposed Changes: {plan.proposed_changes}\n"
            f"- Affected Files: {plan.affected_files}\n"
            f"- Excluded Files: {plan.excluded_files}\n\n"
            "Decision Schema:\n"
            f"{json.dumps(schema)}"
        )

    async def _execute_tool_calls(
        self,
        session: CodingSession,
        tool_calls: list[LLMToolCall],
        plan: EngineeringPlan,
        context: ToolContext,
    ) -> None:
        """Execute a batch of tool calls."""
        for llm_tc in tool_calls:
            session.tool_call_count += 1
            if session.tool_call_count > self.max_tool_calls:
                raise SecurityViolationError("Tool call budget exceeded.")

            try:
                tool = self.tool_registry.get(llm_tc.name)
            except Exception as e:
                self.messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=llm_tc.id,
                        content=json.dumps({"error": f"Unknown tool: {e}"}),
                    )
                )
                continue

            try:
                # Authorize
                CodingPolicy.authorize_tool(
                    tool_name=tool.definition.name,
                    arguments=llm_tc.arguments,
                    capability=tool.definition.capability,
                    phase=session.current_phase,
                    plan=plan,
                    workspace_root=context.workspace_root,
                )

                call = ToolCall(
                    call_id=llm_tc.id, name=llm_tc.name, arguments=llm_tc.arguments
                )
                result = await tool.execute(call, context)

                # Truncate output if necessary
                output_str = str(result.output) if result.success else str(result.error)
                if len(output_str) > self.max_output_size:
                    output_str = output_str[: self.max_output_size] + "... (truncated)"

                if result.success:
                    payload = {"result": output_str}
                else:
                    payload = {"error": output_str}

            except SecurityViolationError as e:
                payload = {"error": f"Security Violation: {e}"}
            except Exception as e:
                payload = {"error": f"Tool execution failed: {e}"}

            self.messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=llm_tc.id,
                    content=json.dumps(payload),
                )
            )

    async def _run_iteration(
        self,
        session: CodingSession,
        plan: EngineeringPlan,
        context: ToolContext,
    ) -> CodingDecision | None:
        """Run a single LLM iteration."""
        schemas = self.tool_registry.get_openai_schemas()

        request = LLMRequest(
            model="default",
            messages=self.messages,
            temperature=0.0,
            tools=schemas,
        )
        response = await self.llm_client.generate(request)

        self.messages.append(
            LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )

        if response.tool_calls:
            await self._execute_tool_calls(session, response.tool_calls, plan, context)
            return None

        # Parse decision
        try:
            content = response.content or ""
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            data = json.loads(content.strip())
            return CodingDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise AgentDecisionParseError(f"Failed to parse CodingDecision: {e}") from e

    async def _rollback(self, session: CodingSession) -> None:
        """Safely restore the checkpoint."""
        if not session.checkpoint_hash or not session.branch:
            return

        checkpoint = WorkspaceCheckpoint(
            task_id=session.task_id,
            commit_hash=session.checkpoint_hash,
            branch=session.branch,
            status=await self.git_service.get_status(),
        )
        try:
            await self.git_service.restore_checkpoint(checkpoint)
        except GitError:
            pass  # Rollback failed, but we must not crash the shutdown process

    async def run(
        self,
        task: AgentTask,
        plan: EngineeringPlan,
        workspace_root: Path,
        test_strategy: TestStrategy | None = None,
        memory_context: MemoryContext | None = None,
    ) -> CodingResult:
        """
        Execute the autonomous coding loop.

        Args:
            task: The overall agent task.
            plan: The generated engineering plan.
            workspace_root: The root of the Git workspace.

        Returns:
            The final CodingResult.
        """
        session = CodingSession(
            session_id=str(uuid.uuid4()),
            task_id=task.task_id,
            plan_id=plan.plan_id,
            current_phase=CodingPhase.INITIALIZING,
        )
        context = ToolContext(
            workspace_root=workspace_root, session_id=session.session_id
        )
        validation_results: list[dict[str, Any]] = []
        changed_files: list[str] = []

        try:
            # Workspace Initialization
            status = await self.git_service.get_status()
            if not status.is_clean:
                raise SecurityViolationError(
                    "Workspace must be completely clean before coding."
                )

            branch = await self.git_service.create_branch(
                f"forgeai/task/{task.task_id}"
            )
            session.branch = branch.name

            checkpoint = await self.git_service.create_checkpoint(task.task_id)
            session.checkpoint_hash = checkpoint.commit_hash

            # Initialize and Authorize ChangeSet
            policy = ChangeSetPolicy(workspace_root)
            if not plan.change_set:
                cs = ChangeSet(objective=plan.task_interpretation)
                for f in plan.affected_files:
                    cs.initial_files.append(FileChange(file_path=f, operation=ChangeOperation.MODIFY, rationale="Legacy affected_files adaptation"))
                plan.change_set = cs
            
            authorized_cs = policy.authorize_change_set(plan.change_set, plan.excluded_files)
            if authorized_cs.status == ChangeSetStatus.REJECTED:
                raise SecurityViolationError("ChangeSet was rejected due to policy violations or empty scope.")
            plan.change_set = authorized_cs
            plan.affected_files = authorized_cs.authorized_files # sync for backward compatibility

            # Setup system prompt
            user_prompt_parts = ["Begin inspection phase. Understand the context before modifying."]
            if memory_context:
                user_prompt_parts.append(memory_context.to_structured_string())

            self.messages = [
                LLMMessage(role="system", content=self._get_system_prompt(plan)),
                LLMMessage(
                    role="user",
                    content="\n\n".join(user_prompt_parts),
                ),
            ]

            session.current_phase = CodingPhase.INSPECTING

            # Main Coding Loop
            while session.current_phase in (
                CodingPhase.INSPECTING,
                CodingPhase.IMPLEMENTING,
                CodingPhase.VALIDATING,
                CodingPhase.REPAIRING,
                CodingPhase.REVIEWING,
            ):
                if session.current_phase == CodingPhase.REVIEWING:
                    status_after = await self.git_service.get_status()
                    diff_after = await self.git_service.get_diff()
                    current_changed_files = [
                        c.path for c in (status_after.staged_changes + status_after.unstaged_changes + status_after.untracked_changes)
                    ]

                    if settings.review_enabled and self.review_agent:
                        session.review_count += 1
                        if session.review_count > settings.review_max_iterations:
                            raise SecurityViolationError("Review iteration budget exceeded.")

                        review_result = await self.review_agent.run(
                            task=task,
                            plan=plan,
                            diff=diff_after,
                            changed_files=current_changed_files,
                            validation_results=validation_results,
                            context=context,
                        )
                        
                        if review_result.status == ReviewStatus.REJECTED:
                            error_msg = f"Review rejected: {review_result.error_message or 'Critical findings.'}"
                            raise SecurityViolationError(error_msg)
                        elif review_result.status == ReviewStatus.CHANGES_REQUIRED:
                            # Loop back to repairing
                            session.current_phase = CodingPhase.REPAIRING
                            findings_str = "\n".join(f"- {f.severity}: {f.description}" for f in review_result.findings)
                            self.messages.append(
                                LLMMessage(
                                    role="user",
                                    content=f"Code Review found issues that require changes:\n{findings_str}\nPlease fix them.",
                                )
                            )
                            continue
                        else:
                            # Approved
                            self.review_result = review_result
                            session.current_phase = CodingPhase.COMPLETED
                    else:
                        session.current_phase = CodingPhase.COMPLETED
                    continue

                if session.current_phase == CodingPhase.VALIDATING and test_strategy and test_strategy.validation_commands:
                    all_passed = True
                    validation_results.clear()
                    
                    try:
                        run_cmd_tool = self.tool_registry.get("run_command")
                    except Exception:
                        run_cmd_tool = None
                    
                    if run_cmd_tool:
                        for cmd in test_strategy.validation_commands:
                            call = ToolCall(call_id=str(uuid.uuid4()), name="run_command", arguments={"command": cmd})
                            res = await run_cmd_tool.execute(call, context)
                            
                            output_str = str(res.output) if res.success else str(res.error)
                            if len(output_str) > self.max_output_size:
                                output_str = output_str[:self.max_output_size] + "... [TRUNCATED]"
                            
                            validation_results.append({
                                "command": cmd,
                                "success": res.success,
                                "output": output_str
                            })
                            
                            if not res.success:
                                all_passed = False
                                break
                    else:
                        all_passed = False
                        validation_results.append({"error": "run_command tool not available for validation"})
                    
                    if all_passed:
                        session.current_phase = CodingPhase.REVIEWING
                        continue
                    else:
                        # Validation failed. Use diagnosis agent if available.
                        if self.failure_diagnosis_agent:
                            session.repair_count += 1
                            if session.repair_count > self.max_repair_iterations:
                                raise AgentMaxIterationsError("Repair budget exceeded due to repeated validation failures.")
                            
                            status_after = await self.git_service.get_status()
                            current_changed = [c.path for c in (status_after.staged_changes + status_after.unstaged_changes + status_after.untracked_changes)]
                            
                            diagnosis = await self.failure_diagnosis_agent.diagnose(
                                task=task,
                                plan=plan,
                                strategy=test_strategy,
                                validation_results=validation_results,
                                changed_files=current_changed
                            )
                            
                            if diagnosis.status == DiagnosisStatus.INFRASTRUCTURE_FAILURE:
                                raise SecurityViolationError("Infrastructure failure detected during validation. Halting repair loop.")
                            
                            if diagnosis.repair_plan:
                                session.current_phase = CodingPhase.REPAIRING
                                plan_str = json.dumps(diagnosis.repair_plan.model_dump(), indent=2)
                                self.messages.append(
                                    LLMMessage(
                                        role="user",
                                        content=f"Validation failed. The Failure Diagnosis Agent proposed this repair plan:\n{plan_str}\n\nPlease execute these targeted repairs.",
                                    )
                                )
                                continue
                            else:
                                raise SecurityViolationError("Validation failed and no valid repair plan was generated.")
                        else:
                            # Fall back to LLM-driven REPAIRING if no diagnosis agent
                            session.repair_count += 1
                            if session.repair_count > self.max_repair_iterations:
                                raise AgentMaxIterationsError("Repair budget exceeded.")
                            session.current_phase = CodingPhase.REPAIRING
                            self.messages.append(
                                LLMMessage(
                                    role="user",
                                    content=f"Validation failed deterministically:\n{validation_results[-1]}\nTransitioning to REPAIRING phase.",
                                )
                            )
                            continue

                if session.iteration_count >= self.max_iterations:
                    raise AgentMaxIterationsError("Iteration budget exceeded.")
                session.iteration_count += 1

                try:
                    decision = await self._run_iteration(session, plan, context)
                except AgentDecisionParseError as e:
                    self.messages.append(
                        LLMMessage(
                            role="user",
                            content=f"Error parsing decision: {e}. Please respond with valid JSON.",
                        )
                    )
                    continue

                if decision:
                    if decision.completion_requested:
                        if session.current_phase in (
                            CodingPhase.INSPECTING,
                            CodingPhase.IMPLEMENTING,
                        ):
                            if settings.coding_run_validation:
                                session.current_phase = CodingPhase.VALIDATING
                                self.messages.append(
                                    LLMMessage(
                                        role="user",
                                        content="Implementation complete. Now run validation tools.",
                                    )
                                )
                            else:
                                session.current_phase = CodingPhase.REVIEWING
                        elif session.current_phase == CodingPhase.VALIDATING:
                            session.current_phase = CodingPhase.REVIEWING
                        elif session.current_phase == CodingPhase.REPAIRING:
                            if settings.coding_run_validation:
                                session.current_phase = CodingPhase.VALIDATING
                                self.messages.append(
                                    LLMMessage(
                                        role="user",
                                        content="Repair complete. Now run validation tools again.",
                                    )
                                )
                            else:
                                session.current_phase = CodingPhase.REVIEWING
                    else:
                        # Advance phase explicitly based on action
                        if (
                            decision.action == "modify"
                            and session.current_phase == CodingPhase.INSPECTING
                        ):
                            session.current_phase = CodingPhase.IMPLEMENTING
                            self.messages.append(
                                LLMMessage(
                                    role="user",
                                    content="Transitioned to IMPLEMENTING phase. You may now mutate authorized files.",
                                )
                            )
                        elif (
                            decision.action == "repair"
                            and session.current_phase == CodingPhase.VALIDATING
                        ):
                            session.repair_count += 1
                            if session.repair_count > self.max_repair_iterations:
                                raise AgentMaxIterationsError("Repair budget exceeded.")
                            session.current_phase = CodingPhase.REPAIRING
                            self.messages.append(
                                LLMMessage(
                                    role="user",
                                    content="Transitioned to REPAIRING phase.",
                                )
                            )

            # Determine changed files for final response if REVIEWING completed without review_agent
            status_after = await self.git_service.get_status()
            diff_after = await self.git_service.get_diff()
            for change in (
                status_after.staged_changes
                + status_after.unstaged_changes
                + status_after.untracked_changes
            ):
                changed_files.append(change.path)

            session.changed_files_count = len(changed_files)
            if session.changed_files_count > self.max_changed_files:
                raise SecurityViolationError(
                    f"Changed {session.changed_files_count} files, exceeding budget of {self.max_changed_files}."
                )

            # Verify authorization for changed files
            for file_path in changed_files:
                resolved_target = resolve_safe_path(workspace_root, file_path)

                # Check excluded
                for excl in plan.excluded_files:
                    try:
                        excl_path = (workspace_root / excl).resolve()
                        if (
                            resolved_target == excl_path
                            or resolved_target.is_relative_to(excl_path)
                        ):
                            raise SecurityViolationError(
                                f"Excluded file was modified: {file_path}"
                            )
                    except ValueError:
                        pass

                # Check affected
                is_affected = False
                if plan.change_set and plan.change_set.status == ChangeSetStatus.AUTHORIZED:
                    try:
                        norm_path = str(resolved_target.relative_to(workspace_root).as_posix())
                        if norm_path in plan.change_set.authorized_files:
                            is_affected = True
                    except ValueError:
                        pass
                else:
                    for aff in plan.affected_files:
                        try:
                            aff_path = (workspace_root / aff).resolve()
                            if (
                                resolved_target == aff_path
                                or resolved_target.is_relative_to(aff_path)
                            ):
                                is_affected = True
                                break
                        except ValueError:
                            pass

                if not is_affected:
                    raise SecurityViolationError(
                        f"Unauthorized file was modified: {file_path}. Not in authorized ChangeSet."
                    )
                
            # ChangeSet Completeness Check
            if plan.change_set and plan.change_set.status == ChangeSetStatus.AUTHORIZED:
                # If a file was authorized for deletion, make sure it is actually deleted.
                # (Git status shows D for deleted, which gets included in changed_files,
                # so the file shouldn't exist on disk)
                for df in plan.change_set.deleted_files:
                    try:
                        resolved_df = resolve_safe_path(workspace_root, df)
                        if resolved_df.exists():
                            raise SecurityViolationError(
                                f"ChangeSet completeness check failed: File '{df}' was scheduled for deletion but still exists."
                            )
                    except ValueError:
                        pass
                
                # Check created files exist
                for cf in plan.change_set.created_files:
                    try:
                        resolved_cf = resolve_safe_path(workspace_root, cf)
                        if not resolved_cf.exists():
                            raise SecurityViolationError(
                                f"ChangeSet completeness check failed: File '{cf}' was scheduled for creation but does not exist."
                            )
                    except ValueError:
                        pass

            session.current_phase = CodingPhase.COMPLETED

            committed = False
            commit_hash = None
            if settings.coding_auto_commit and changed_files:
                await self.git_service.stage_files(changed_files)
                commit_obj = await self.git_service.commit(
                    message=f"Agent completed task {task.task_id}", paths=changed_files
                )
                committed = True
                commit_hash = commit_obj.commit_hash

            return CodingResult(
                task_id=task.task_id,
                success=True,
                final_phase=session.current_phase,
                session=session,
                changed_files=changed_files,
                validation_results=validation_results,
                committed=committed,
                commit_hash=commit_hash,
                review_result=getattr(self, "review_result", None),
                summary="Coding task completed successfully.",
            )

        except (
            SecurityViolationError,
            AgentMaxIterationsError,
            LLMError,
            GitError,
        ) as e:
            session.current_phase = CodingPhase.FAILED

            # Rollback
            await self._rollback(session)
            session.current_phase = CodingPhase.ROLLED_BACK

            return CodingResult(
                task_id=task.task_id,
                success=False,
                final_phase=session.current_phase,
                session=session,
                changed_files=[],
                validation_results=validation_results,
                error_message=str(e),
                summary="Coding task failed and was rolled back.",
            )
        except Exception as e:
            session.current_phase = CodingPhase.FAILED
            await self._rollback(session)
            session.current_phase = CodingPhase.ROLLED_BACK
            return CodingResult(
                task_id=task.task_id,
                success=False,
                final_phase=session.current_phase,
                session=session,
                changed_files=[],
                validation_results=validation_results,
                error_message=str(e),
                summary=f"Unexpected failure: {e}",
            )
