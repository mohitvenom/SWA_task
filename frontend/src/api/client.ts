export interface ExecuteRequest {
  task: string;
  workspace_root: string;
  execution_id?: string;
}

export interface ExecutionResult {
  execution_id: string;
  task_id: string;
  status: string;
  summary: string;
  duration: number;
  failure_information?: string;
  changed_files?: string[];
  validation_results?: any[];
  review_result?: any;
  repair_count?: number;
  git_result?: {
    commit_hash?: string;
    branch?: string;
  };
}

export interface ExecutionEvent {
  event_id: string;
  execution_id: string;
  timestamp: string;
  event_type: string;
  phase: string;
  summary: string;
  metadata?: Record<string, any>;
}

export class APIError extends Error {
  status: number;
  data: any;
  
  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.data = data;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_URL = API_BASE_URL;

export interface SettingsResponse {
  autonomous_execution_enabled: boolean;
  max_execution_duration: number;
  memory_enabled: boolean;
  llm_provider_configured: boolean;
  llm_default_model: string | null;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/health`);
    return response.ok;
  } catch (error) {
    return false;
  }
}

export async function fetchSettings(): Promise<SettingsResponse> {
  const response = await fetch(`${API_URL}/settings`);
  if (!response.ok) {
    throw new APIError('Failed to fetch settings', response.status);
  }
  return response.json();
}

export async function executeTask(req: ExecuteRequest): Promise<ExecutionResult> {
  const response = await fetch(`${API_URL}/execute`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    let errorMsg = 'Failed to execute task';
    try {
      const data = await response.json();
      errorMsg = data.detail || errorMsg;
    } catch (e) {
      // ignore JSON parse error on non-JSON response
    }
    throw new APIError(errorMsg, response.status);
  }

  return response.json();
}

export async function getExecutionEvents(executionId: string): Promise<ExecutionEvent[]> {
  const response = await fetch(`${API_URL}/executions/${executionId}/events`);
  if (!response.ok) {
    if (response.status === 404) return [];
    throw new APIError('Failed to fetch events', response.status);
  }
  return response.json();
}

export function subscribeToExecutionEvents(
  executionId: string,
  onEvent: (event: ExecutionEvent) => void,
  onError?: (err: any) => void
): () => void {
  const url = `${API_URL}/executions/${executionId}/events/stream`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (e) => {
    try {
      const event: ExecutionEvent = JSON.parse(e.data);
      onEvent(event);
    } catch (err) {
      console.error('Failed to parse SSE event:', err);
    }
  };

  eventSource.onerror = (e) => {
    if (onError) onError(e);
  };

  return () => {
    eventSource.close();
  };
}
