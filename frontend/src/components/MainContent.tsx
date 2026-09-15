import React, { useState, useEffect } from 'react';
import { executeTask, type ExecutionResult, APIError, getExecutionEvents, type ExecutionEvent, subscribeToExecutionEvents } from '../api/client';
import ExecutionWorkflow from './ExecutionWorkflow';
import { saveExecutionToHistory } from '../api/history';

type ExecutionState = 'idle' | 'executing' | 'completed' | 'failed';

interface MainContentProps {
  initialTask?: { task: string; workspace: string } | null;
}

const MainContent: React.FC<MainContentProps> = ({ initialTask }) => {
  const [workspaceRoot, setWorkspaceRoot] = useState('/workspace/current-project');
  const [task, setTask] = useState('');
  const [executionState, setExecutionState] = useState<ExecutionState>('idle');
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<ExecutionEvent[]>([]);

  useEffect(() => {
    if (initialTask) {
      setTask(initialTask.task);
      setWorkspaceRoot(initialTask.workspace);
    }
  }, [initialTask]);

  const handleExecute = async () => {
    if (!task.trim() || !workspaceRoot.trim()) return;
    
    setExecutionState('executing');
    setErrorMsg(null);
    setResult(null);
    setLiveEvents([]);

    const executionId = crypto.randomUUID();
    
    const unsubscribe = subscribeToExecutionEvents(
      executionId,
      (event) => {
        setLiveEvents((prev) => {
          if (prev.some(e => e.event_id === event.event_id)) return prev;
          return [...prev, event];
        });
      },
      (_err) => {
        // SSE errors are mostly ignored as they auto-reconnect, but if we need to log them we can
      }
    );

    try {
      const res = await executeTask({ workspace_root: workspaceRoot, task, execution_id: executionId });
      unsubscribe();
      
      // Final fetch to ensure we have all events just in case SSE was disconnected right before end
      try {
        const finalEvents = await getExecutionEvents(executionId);
        setLiveEvents(finalEvents);
      } catch (e) {}

      setResult(res);
      setExecutionState('completed');
      saveExecutionToHistory(task, workspaceRoot, res, res.execution_id || executionId);
    } catch (err: any) {
      unsubscribe();
      try {
        const finalEvents = await getExecutionEvents(executionId);
        setLiveEvents(finalEvents);
      } catch (e) {}
      
      setExecutionState('failed');
      const failMsg = err instanceof APIError ? err.message : (err.message || 'An unexpected error occurred. Please check network connection.');
      setErrorMsg(failMsg);
      
      // Save failed executions to history for debugging and auditing
      saveExecutionToHistory(task, workspaceRoot, {
        execution_id: executionId,
        task_id: '',
        status: 'FAILED',
        summary: 'Execution failed due to network or API error.',
        changed_files: [],
        validation_results: [],
        repair_count: 0,
        duration: 0,
        failure_information: failMsg,
      }, executionId);
    }
  };

  const resetForm = () => {
    setExecutionState('idle');
    setResult(null);
    setErrorMsg(null);
    setTask('');
  };

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-[var(--background)]">
      {/* Header Area */}
      <header className="h-16 flex items-center justify-between px-8 border-b border-[var(--border)] bg-[var(--card)]">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-[var(--muted)]">Status:</span>
          {executionState === 'executing' ? (
            <div className="flex items-center gap-2 px-3 py-1 bg-blue-500/10 text-blue-500 rounded-full text-xs font-medium border border-blue-500/20">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
              Executing Task...
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-1 bg-green-500/10 text-green-500 rounded-full text-xs font-medium border border-green-500/20">
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              System Ready
            </div>
          )}
        </div>
        <div className="flex items-center gap-4">
          <button className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto p-8 flex flex-col items-center">
        <div className="w-full max-w-5xl space-y-8">
          
          <div className="text-center space-y-4 mb-12">
            <h1 className="text-5xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400">
              Autonomous Software Engineer
            </h1>
            <p className="text-lg text-[var(--muted)] max-w-2xl mx-auto font-medium">
              ForgeAI understands context, plans architectures, writes code, tests features, and commits directly to your workspace.
            </p>
          </div>

          {(executionState === 'idle' || executionState === 'executing') && (
            <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden transition-all max-w-4xl mx-auto w-full">
              <div className="p-8 space-y-8">
                
                <div className="space-y-3">
                  <label className="text-sm font-semibold text-[var(--foreground)] flex items-center gap-2">
                    <svg className="w-4 h-4 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                    </svg>
                    Workspace Path
                  </label>
                  <input 
                    type="text" 
                    value={workspaceRoot}
                    onChange={(e) => setWorkspaceRoot(e.target.value)}
                    disabled={executionState === 'executing'}
                    className="w-full bg-[var(--input)] border border-[var(--border)] rounded-lg px-4 py-3.5 text-[var(--foreground)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/50 focus:border-[var(--primary)] transition-all disabled:opacity-50 shadow-inner"
                    placeholder="Enter absolute workspace path..."
                  />
                </div>

                <div className="space-y-3">
                  <label className="text-sm font-semibold text-[var(--foreground)] flex items-center gap-2">
                    <svg className="w-4 h-4 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Task Description
                  </label>
                  <textarea 
                    rows={6}
                    value={task}
                    onChange={(e) => setTask(e.target.value)}
                    disabled={executionState === 'executing'}
                    className="w-full bg-[var(--input)] border border-[var(--border)] rounded-lg px-4 py-3.5 text-[var(--foreground)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/50 focus:border-[var(--primary)] transition-all resize-none disabled:opacity-50 shadow-inner"
                    placeholder="Describe what you want me to build or change in the codebase..."
                  ></textarea>
                  
                  {executionState === 'idle' && (
                    <div className="pt-4">
                      <p className="text-xs font-medium text-[var(--muted)] mb-3 uppercase tracking-wider">Try an example</p>
                      <div className="flex flex-wrap gap-2">
                        {[
                          "Create a Python utility function to reverse a string and write unit tests.",
                          "Fix any failing tests in the math module.",
                          "Add basic input validation to the User registration endpoint.",
                          "Create a new generic README.md file in the root with standard setup instructions."
                        ].map((example, idx) => (
                          <button
                            key={idx}
                            onClick={() => setTask(example)}
                            className="text-xs px-3 py-1.5 rounded-full bg-[var(--input)] border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)]/50 transition-colors"
                          >
                            {example}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

              </div>
              
              <div className="bg-[var(--input)] px-8 py-5 flex items-center justify-between border-t border-[var(--border)]">
                <span className="text-sm font-medium text-[var(--muted)] flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {executionState === 'executing' ? 'Execution in progress...' : 'Ready to execute'}
                </span>
                <button 
                  onClick={handleExecute}
                  disabled={executionState === 'executing' || !task.trim() || !workspaceRoot.trim()}
                  className="relative overflow-hidden group bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white px-8 py-3 rounded-lg text-sm font-bold transition-all flex items-center gap-2 shadow-[0_0_20px_rgba(59,130,246,0.3)] hover:shadow-[0_0_25px_rgba(59,130,246,0.5)] disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
                >
                  <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300 ease-out rounded-lg pointer-events-none"></div>
                  <span className="relative z-10 flex items-center gap-2">
                    {executionState === 'executing' ? 'Executing...' : 'Execute Task'}
                    {executionState === 'executing' ? (
                      <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    ) : (
                      <svg className="w-5 h-5 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                      </svg>
                    )}
                  </span>
                </button>
              </div>
            </div>
          )}

          {/* Results Area */}
          {(executionState === 'completed' || executionState === 'failed') && (
            <div className={`border rounded-xl shadow-2xl overflow-hidden transition-all max-w-4xl mx-auto w-full ${
              executionState === 'completed' && result?.status === 'COMPLETED' ? 'border-green-500/30 bg-[var(--card)]' : 
              executionState === 'completed' && result?.status === 'NEEDS_CLARIFICATION' ? 'border-amber-500/30 bg-[var(--card)]' :
              executionState === 'completed' && result?.status === 'ROLLED_BACK' ? 'border-orange-500/30 bg-[var(--card)]' :
              'border-red-500/30 bg-[var(--card)]'
            }`}>
              <div className={`p-6 border-b ${
                executionState === 'completed' && result?.status === 'COMPLETED' ? 'bg-gradient-to-r from-green-500/10 to-transparent border-green-500/20' : 
                executionState === 'completed' && result?.status === 'NEEDS_CLARIFICATION' ? 'bg-gradient-to-r from-amber-500/10 to-transparent border-amber-500/20' :
                executionState === 'completed' && result?.status === 'ROLLED_BACK' ? 'bg-gradient-to-r from-orange-500/10 to-transparent border-orange-500/20' :
                'bg-gradient-to-r from-red-500/10 to-transparent border-red-500/20'
              }`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    {executionState === 'completed' && result?.status === 'COMPLETED' ? (
                      <div className="w-12 h-12 rounded-full bg-green-500/20 text-green-400 flex items-center justify-center shadow-[0_0_15px_rgba(34,197,94,0.3)]">
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                    ) : executionState === 'completed' && result?.status === 'NEEDS_CLARIFICATION' ? (
                      <div className="w-12 h-12 rounded-full bg-amber-500/20 text-amber-400 flex items-center justify-center shadow-[0_0_15px_rgba(245,158,11,0.3)]">
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      </div>
                    ) : executionState === 'completed' && result?.status === 'ROLLED_BACK' ? (
                      <div className="w-12 h-12 rounded-full bg-orange-500/20 text-orange-400 flex items-center justify-center shadow-[0_0_15px_rgba(249,115,22,0.3)]">
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                        </svg>
                      </div>
                    ) : (
                      <div className="w-12 h-12 rounded-full bg-red-500/20 text-red-400 flex items-center justify-center shadow-[0_0_15px_rgba(239,68,68,0.3)]">
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </div>
                    )}
                    <div>
                      <h2 className="text-2xl font-black tracking-tight text-[var(--foreground)]">
                        {result?.status || (executionState === 'failed' ? 'FAILED' : 'UNKNOWN')}
                      </h2>
                      <p className="text-sm font-medium text-[var(--muted)]">
                        {result?.execution_id ? `ID: ${result.execution_id.substring(0, 8)}` : 'Internal Error'} 
                        {result && ` • Duration: ${result.duration.toFixed(1)}s`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {(executionState === 'failed' || (result && result.status !== 'COMPLETED')) && (
                      <button 
                        onClick={() => {
                          setExecutionState('idle');
                        }}
                        className="text-sm font-bold px-5 py-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded-lg transition-colors border border-red-500/20 shadow-sm"
                      >
                        Edit & Retry
                      </button>
                    )}
                    <button 
                      onClick={resetForm}
                      className="text-sm font-bold px-5 py-2.5 bg-[var(--card)] hover:bg-[var(--accent)] text-[var(--foreground)] rounded-lg transition-colors border border-[var(--border)] shadow-sm hover:shadow-md"
                    >
                      Run New Task
                    </button>
                  </div>
                </div>
              </div>

              <div className="p-8 space-y-8">
                {errorMsg && (
                  <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm font-medium flex items-start gap-3">
                    <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>{errorMsg}</span>
                  </div>
                )}
                
                {result && (
                  <div className="space-y-8">
                    {/* Summary Section */}
                    <div>
                      <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-3">Execution Summary</h3>
                      <div className="bg-[var(--input)] p-5 rounded-xl border border-[var(--border)] shadow-inner">
                        <p className="text-sm text-[var(--foreground)] leading-relaxed whitespace-pre-wrap">{result.summary}</p>
                        {result.failure_information && (
                          <div className="mt-5 pt-5 border-t border-[var(--border)]">
                            <p className="text-sm text-red-400 font-mono whitespace-pre-wrap p-3 bg-red-500/5 rounded border border-red-500/10">{result.failure_information}</p>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Metrics Section */}
                    <div>
                      <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-3">Metrics</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="p-5 bg-gradient-to-br from-[var(--input)] to-[var(--card)] rounded-xl border border-[var(--border)] shadow-sm hover:border-blue-500/30 transition-colors group">
                          <span className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider block mb-1 group-hover:text-blue-400 transition-colors">Changed Files</span>
                          <span className="text-3xl font-black text-[var(--foreground)]">{result.changed_files?.length || 0}</span>
                        </div>
                        <div className="p-5 bg-gradient-to-br from-[var(--input)] to-[var(--card)] rounded-xl border border-[var(--border)] shadow-sm hover:border-blue-500/30 transition-colors group">
                          <span className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider block mb-1 group-hover:text-blue-400 transition-colors">Repair Attempts</span>
                          <span className="text-3xl font-black text-[var(--foreground)]">{result.repair_count || 0}</span>
                        </div>
                        <div className="p-5 bg-gradient-to-br from-[var(--input)] to-[var(--card)] rounded-xl border border-[var(--border)] shadow-sm hover:border-blue-500/30 transition-colors group">
                          <span className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider block mb-1 group-hover:text-blue-400 transition-colors">Tests Run</span>
                          <span className="text-3xl font-black text-[var(--foreground)]">{result.validation_results?.length || 0}</span>
                        </div>
                        <div className="p-5 bg-gradient-to-br from-[var(--input)] to-[var(--card)] rounded-xl border border-[var(--border)] shadow-sm hover:border-blue-500/30 transition-colors group">
                          <span className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider block mb-1 group-hover:text-blue-400 transition-colors">Duration</span>
                          <span className="text-3xl font-black text-[var(--foreground)]">{result.duration.toFixed(1)}s</span>
                        </div>
                      </div>
                    </div>

                    {/* Changed Files Section */}
                    {result.changed_files && result.changed_files.length > 0 && (
                      <div>
                        <h3 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-3">Changed Files ({result.changed_files.length})</h3>
                        <div className="bg-[var(--input)] rounded-xl border border-[var(--border)] shadow-inner overflow-hidden">
                          <ul className="divide-y divide-[var(--border)] max-h-60 overflow-y-auto">
                            {result.changed_files.map((file, idx) => {
                              const isPython = file.endsWith('.py');
                              const isTs = file.endsWith('.ts') || file.endsWith('.tsx');
                              const isMd = file.endsWith('.md');
                              
                              return (
                                <li key={idx} className="flex items-center justify-between px-5 py-3 hover:bg-[var(--accent)]/50 transition-colors group">
                                  <div className="flex items-center gap-3 overflow-hidden">
                                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center border ${
                                      isPython ? 'bg-yellow-500/10 border-yellow-500/20 text-yellow-500' :
                                      isTs ? 'bg-blue-500/10 border-blue-500/20 text-blue-500' :
                                      isMd ? 'bg-zinc-500/10 border-zinc-500/20 text-zinc-400' :
                                      'bg-[var(--muted)]/10 border-[var(--muted)]/20 text-[var(--muted)]'
                                    }`}>
                                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                      </svg>
                                    </div>
                                    <span className="text-sm font-medium text-[var(--foreground)] font-mono truncate">{file}</span>
                                  </div>
                                  <div className="flex items-center text-[var(--muted)] group-hover:text-blue-400 transition-colors opacity-0 group-hover:opacity-100">
                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                    </svg>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      </div>
                    )}

                    {/* Git Checkpoint Section */}
                    {result.git_result && (
                      <div>
                        <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Git Checkpoint</h3>
                        <div className="bg-[var(--input)] px-4 py-3 rounded-lg border border-[var(--border)] text-sm font-mono flex items-center justify-between text-[var(--foreground)]">
                          <div className="flex items-center gap-2">
                            <svg className="w-4 h-4 text-[var(--muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
                            </svg>
                            <span>Commit: {result.git_result.commit_hash?.substring(0, 7) || 'N/A'}</span>
                          </div>
                          {result.git_result.branch && (
                            <span className="px-2 py-1 bg-[var(--accent)] rounded text-xs">{result.git_result.branch}</span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="pt-8 pb-12">
            <ExecutionWorkflow 
              executionState={executionState} 
              resultStatus={result?.status} 
              liveEvents={liveEvents}
            />
          </div>

        </div>
      </main>
    </div>
  );
};

export default MainContent;
