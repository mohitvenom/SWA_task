"""ChangeSet authorization and validation policy."""

import re
from pathlib import Path

from forgeai.agents.errors import ChangeSetValidationError
from forgeai.agents.models import (
    ChangeOperation,
    ChangeSet,
    ChangeSetStatus,
    ScopeExpansionDecision,
    ScopeExpansionReason,
    ScopeExpansionRecord,
    ScopeExpansionRequest,
)
from forgeai.config.settings import settings
from forgeai.tools.repository.utils import resolve_safe_path


class ChangeSetPolicy:
    """Policy for validating and authorizing ChangeSets."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.max_files = settings.coding_max_changed_files
        self._sensitive_patterns = [
            r"^\.env.*",
            r"^.*\.pem$",
            r"^.*\.key$",
            r"^.*_rsa$",
        ]

    def _is_sensitive(self, file_name: str) -> bool:
        for pattern in self._sensitive_patterns:
            if re.match(pattern, file_name):
                return True
        return False

    def authorize_change_set(
        self,
        proposed_change_set: ChangeSet,
        excluded_files: list[str]
    ) -> ChangeSet:
        """
        Validate and authorize a proposed ChangeSet based on strict security and limit rules.
        """
        authorized_files: set[str] = set()
        created_files: set[str] = set()
        modified_files: set[str] = set()
        deleted_files: set[str] = set()

        resolved_excluded: set[Path] = set()
        for excl in excluded_files:
            try:
                resolved_excluded.add(resolve_safe_path(self.workspace_root, excl))
            except Exception:
                pass
        
        # Reset expansion history for fresh authorization run
        proposed_change_set.expansion_history = []
        
        all_requests = []
        
        for fc in proposed_change_set.initial_files:
            all_requests.append((fc, ScopeExpansionRequest(
                file_path=fc.file_path,
                reason=ScopeExpansionReason.EXPLICIT_REQUEST,
                rationale=fc.rationale,
                source_evidence="Initial plan proposal"
            )))
            
        for fc in proposed_change_set.discovered_files:
            all_requests.append((fc, ScopeExpansionRequest(
                file_path=fc.file_path,
                reason=ScopeExpansionReason.DEPENDENCY_DISCOVERY,
                rationale=fc.rationale,
                source_evidence="Dependency discovery"
            )))

        for fc, req in all_requests:
            try:
                if Path(req.file_path).is_absolute():
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_OUT_OF_BOUNDS,
                        decision_reason="Absolute paths are forbidden."
                    )
                    proposed_change_set.expansion_history.append(record)
                    continue
                    
                if ".." in Path(req.file_path).parts:
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_OUT_OF_BOUNDS,
                        decision_reason="Path traversal is forbidden."
                    )
                    proposed_change_set.expansion_history.append(record)
                    continue

                resolved = resolve_safe_path(self.workspace_root, req.file_path)

                if self._is_sensitive(resolved.name):
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_SENSITIVE,
                        decision_reason="File is sensitive."
                    )
                    proposed_change_set.expansion_history.append(record)
                    continue

                is_excluded = False
                for excl in resolved_excluded:
                    if resolved == excl or resolved.is_relative_to(excl):
                        is_excluded = True
                        break
                
                if is_excluded:
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_EXCLUDED,
                        decision_reason="File is explicitly excluded."
                    )
                    proposed_change_set.expansion_history.append(record)
                    continue

                norm_path = str(resolved.relative_to(self.workspace_root).as_posix())
                
                if norm_path in authorized_files:
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_DUPLICATE,
                        decision_reason="File is already authorized."
                    )
                    proposed_change_set.expansion_history.append(record)
                    
                    if fc.operation == ChangeOperation.CREATE:
                        created_files.add(norm_path)
                    elif fc.operation == ChangeOperation.MODIFY:
                        modified_files.add(norm_path)
                    elif fc.operation == ChangeOperation.DELETE:
                        deleted_files.add(norm_path)
                    continue

                if len(authorized_files) >= self.max_files:
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_LIMIT_EXCEEDED,
                        decision_reason="Maximum authorized files limit exceeded."
                    )
                    proposed_change_set.expansion_history.append(record)
                    continue
                
                authorized_files.add(norm_path)
                
                if fc.operation == ChangeOperation.CREATE:
                    created_files.add(norm_path)
                elif fc.operation == ChangeOperation.MODIFY:
                    modified_files.add(norm_path)
                elif fc.operation == ChangeOperation.DELETE:
                    deleted_files.add(norm_path)
                    
                record = ScopeExpansionRecord(
                    request=req,
                    decision=ScopeExpansionDecision.APPROVED,
                    decision_reason="File authorized."
                )
                proposed_change_set.expansion_history.append(record)

            except Exception as e:
                msg = str(e)
                if "sensitive" in msg.lower():
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_SENSITIVE,
                        decision_reason=msg
                    )
                else:
                    record = ScopeExpansionRecord(
                        request=req,
                        decision=ScopeExpansionDecision.REJECTED_OUT_OF_BOUNDS,
                        decision_reason=msg
                    )
                proposed_change_set.expansion_history.append(record)
        
        proposed_change_set.authorized_files = sorted(list(authorized_files))
        proposed_change_set.created_files = sorted(list(created_files))
        proposed_change_set.modified_files = sorted(list(modified_files))
        proposed_change_set.deleted_files = sorted(list(deleted_files))
        
        if not proposed_change_set.authorized_files and (proposed_change_set.initial_files or proposed_change_set.discovered_files):
            proposed_change_set.status = ChangeSetStatus.REJECTED
        else:
            proposed_change_set.status = ChangeSetStatus.AUTHORIZED

        return proposed_change_set
