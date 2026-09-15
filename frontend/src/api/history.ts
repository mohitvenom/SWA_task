import type { ExecutionResult } from './client';

export interface ExecutionHistoryItem {
  id: string;
  timestamp: string;
  task: string;
  workspace: string;
  status: string;
  duration: number;
  changedFilesCount: number;
  repairCount: number;
  gitCommit?: { hash: string; branch?: string };
  summary: string;
  failureInformation?: string;
}

const HISTORY_KEY = 'forgeai_execution_history';
const MAX_ENTRIES = 50;

export function getExecutionHistory(): ExecutionHistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed as ExecutionHistoryItem[];
    }
    return [];
  } catch (error) {
    console.error('Failed to read execution history from localStorage:', error);
    return [];
  }
}

export function saveExecutionToHistory(
  task: string,
  workspace: string,
  result: ExecutionResult,
  executionId: string = crypto.randomUUID()
): void {
  try {
    const newItem: ExecutionHistoryItem = {
      id: executionId,
      timestamp: new Date().toISOString(),
      task,
      workspace,
      status: result.status,
      duration: result.duration,
      changedFilesCount: result.changed_files?.length || 0,
      repairCount: result.repair_count || 0,
      summary: result.summary,
      failureInformation: result.failure_information,
    };

    if (result.git_result?.commit_hash) {
      newItem.gitCommit = {
        hash: result.git_result.commit_hash,
        branch: result.git_result.branch,
      };
    }

    const currentHistory = getExecutionHistory();
    // prevent accidental duplicate entries based on execution_id
    if (currentHistory.some(item => item.id === result.execution_id || item.id === executionId)) {
      return;
    }

    const updatedHistory = [newItem, ...currentHistory].slice(0, MAX_ENTRIES);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(updatedHistory));
  } catch (error) {
    console.error('Failed to save execution history to localStorage:', error);
  }
}

export function clearExecutionHistory(): void {
  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch (error) {
    console.error('Failed to clear execution history from localStorage:', error);
  }
}
