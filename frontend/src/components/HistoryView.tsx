import React, { useState, useEffect } from 'react';
import { getExecutionHistory, clearExecutionHistory, type ExecutionHistoryItem } from '../api/history';
import ExecutionWorkflow from './ExecutionWorkflow';

// Reusing similar layout logic from MainContent, but adapted for History 
// To avoid massive duplication, we could extract the Result view, but keeping it here for isolated history concern

interface HistoryViewProps {
  onReopenTask: (task: string, workspace: string) => void;
}

const HistoryView: React.FC<HistoryViewProps> = ({ onReopenTask }) => {
  const [history, setHistory] = useState<ExecutionHistoryItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<ExecutionHistoryItem | null>(null);
  
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [sortOrder, setSortOrder] = useState<'NEWEST' | 'OLDEST'>('NEWEST');

  useEffect(() => {
    setHistory(getExecutionHistory());
  }, []);

  const handleClear = () => {
    if (window.confirm('Are you sure you want to clear all execution history? This cannot be undone.')) {
      clearExecutionHistory();
      setHistory([]);
      setSelectedItem(null);
    }
  };

  const getStatusColor = (status: string) => {
    if (status === 'COMPLETED') return 'text-green-500 bg-green-500/10 border-green-500/20';
    return 'text-red-500 bg-red-500/10 border-red-500/20';
  };

  if (selectedItem) {
    // Show Details View
    const isCompleted = selectedItem.status === 'COMPLETED';
    
    return (
      <div className="flex-1 flex flex-col h-screen overflow-hidden bg-[var(--background)]">
        <header className="h-16 flex items-center justify-between px-8 border-b border-[var(--border)] bg-[var(--card)]">
          <div className="flex items-center gap-4">
            <button 
              onClick={() => setSelectedItem(null)}
              className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors flex items-center gap-2"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              Back to History
            </button>
            <span className="text-[var(--border)]">|</span>
            <span className="text-sm font-medium text-[var(--foreground)] truncate max-w-md">
              {selectedItem.task}
            </span>
          </div>
          <button 
            onClick={() => onReopenTask(selectedItem.task, selectedItem.workspace)}
            className="text-sm font-medium px-4 py-2 bg-[var(--primary)] hover:bg-blue-600 text-white rounded-lg transition-colors flex items-center gap-2 shadow-lg"
          >
            {isCompleted ? (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Run Similar Task
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                Edit and Retry
              </>
            )}
          </button>
        </header>

        <main className="flex-1 overflow-y-auto p-8 flex flex-col items-center">
          <div className="w-full max-w-5xl space-y-8">
            <div className={`border rounded-xl shadow-xl overflow-hidden transition-all max-w-4xl mx-auto w-full ${
              isCompleted ? 'border-green-500/30 bg-[var(--card)]' : 'border-red-500/30 bg-[var(--card)]'
            }`}>
              <div className={`p-6 border-b ${
                isCompleted ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'
              }`}>
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                    isCompleted ? 'bg-green-500/20 text-green-500' : 'bg-red-500/20 text-red-500'
                  }`}>
                    {isCompleted ? (
                      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    )}
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-[var(--foreground)]">
                      Final Status: {selectedItem.status}
                    </h2>
                    <p className="text-sm text-[var(--muted)]">
                      ID: {selectedItem.id.substring(0, 8)} • Duration: {selectedItem.duration.toFixed(1)}s • {new Date(selectedItem.timestamp).toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>

              <div className="p-6 space-y-6">
                <div>
                  <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Execution Summary</h3>
                  <div className="bg-[var(--input)] p-4 rounded-lg border border-[var(--border)]">
                    <p className="text-sm text-[var(--foreground)] leading-relaxed whitespace-pre-wrap">{selectedItem.summary}</p>
                    {selectedItem.failureInformation && (
                      <div className="mt-4 pt-4 border-t border-[var(--border)]">
                        <p className="text-sm text-red-400 font-mono whitespace-pre-wrap">{selectedItem.failureInformation}</p>
                      </div>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="p-4 bg-[var(--input)] rounded-lg border border-[var(--border)]">
                    <span className="text-xs text-[var(--muted)] uppercase tracking-wider block mb-1">Workspace</span>
                    <span className="text-sm font-bold truncate block" title={selectedItem.workspace}>
                      {selectedItem.workspace.split(/[/\\]/).pop() || selectedItem.workspace}
                    </span>
                  </div>
                  <div className="p-4 bg-[var(--input)] rounded-lg border border-[var(--border)]">
                    <span className="text-xs text-[var(--muted)] uppercase tracking-wider block mb-1">Changed Files</span>
                    <span className="text-2xl font-bold">{selectedItem.changedFilesCount}</span>
                  </div>
                  <div className="p-4 bg-[var(--input)] rounded-lg border border-[var(--border)]">
                    <span className="text-xs text-[var(--muted)] uppercase tracking-wider block mb-1">Repair Attempts</span>
                    <span className="text-2xl font-bold">{selectedItem.repairCount}</span>
                  </div>
                  <div className="p-4 bg-[var(--input)] rounded-lg border border-[var(--border)]">
                    <span className="text-xs text-[var(--muted)] uppercase tracking-wider block mb-1">Duration</span>
                    <span className="text-2xl font-bold">{selectedItem.duration.toFixed(1)}s</span>
                  </div>
                </div>

                {selectedItem.gitCommit && (
                  <div>
                    <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Git Checkpoint</h3>
                    <div className="bg-[var(--input)] px-4 py-3 rounded-lg border border-[var(--border)] text-sm font-mono flex items-center justify-between text-[var(--foreground)]">
                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-[var(--muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
                        </svg>
                        <span>Commit: {selectedItem.gitCommit.hash.substring(0, 7)}</span>
                      </div>
                      {selectedItem.gitCommit.branch && (
                        <span className="px-2 py-1 bg-[var(--accent)] rounded text-xs">{selectedItem.gitCommit.branch}</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="pt-8 pb-12">
              <ExecutionWorkflow 
                executionState={isCompleted ? 'completed' : 'failed'} 
                resultStatus={selectedItem.status} 
              />
            </div>
          </div>
        </main>
      </div>
    );
  }

  // Filter and Sort History
  const filteredHistory = history
    .filter(item => statusFilter === 'ALL' || item.status === statusFilter)
    .filter(item => item.task.toLowerCase().includes(searchQuery.toLowerCase()))
    .sort((a, b) => {
      const dateA = new Date(a.timestamp).getTime();
      const dateB = new Date(b.timestamp).getTime();
      return sortOrder === 'NEWEST' ? dateB - dateA : dateA - dateB;
    });

  // Show List View
  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-[var(--background)]">
      <header className="h-16 flex items-center justify-between px-8 border-b border-[var(--border)] bg-[var(--card)]">
        <h1 className="text-lg font-bold text-[var(--foreground)]">Execution History</h1>
        {history.length > 0 && (
          <button 
            onClick={handleClear}
            className="text-sm font-medium px-4 py-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
          >
            Clear History
          </button>
        )}
      </header>

      <main className="flex-1 overflow-y-auto p-8 flex flex-col items-center">
        <div className="w-full max-w-4xl space-y-6">
          
          {history.length > 0 && (
            <div className="flex flex-col md:flex-row gap-4 bg-[var(--card)] p-4 rounded-xl border border-[var(--border)]">
              <div className="flex-1">
                <input 
                  type="text" 
                  placeholder="Search tasks..." 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-[var(--input)] border border-[var(--border)] rounded-lg px-4 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex gap-4">
                <select 
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="bg-[var(--input)] border border-[var(--border)] rounded-lg px-4 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-blue-500"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="COMPLETED">Completed</option>
                  <option value="FAILED">Failed</option>
                  <option value="ROLLED_BACK">Rolled Back</option>
                  <option value="SECURITY_REJECTED">Security Rejected</option>
                  <option value="NEEDS_CLARIFICATION">Needs Clarification</option>
                </select>
                <select 
                  value={sortOrder}
                  onChange={(e) => setSortOrder(e.target.value as 'NEWEST' | 'OLDEST')}
                  className="bg-[var(--input)] border border-[var(--border)] rounded-lg px-4 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-blue-500"
                >
                  <option value="NEWEST">Newest First</option>
                  <option value="OLDEST">Oldest First</option>
                </select>
              </div>
            </div>
          )}

          {filteredHistory.length === 0 ? (
            <div className="text-center py-20 border-2 border-dashed border-[var(--border)] rounded-xl bg-[var(--card)]">
              <svg className="w-12 h-12 text-[var(--muted)] mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <h3 className="text-lg font-medium text-[var(--foreground)] mb-2">No Execution History</h3>
              <p className="text-sm text-[var(--muted)] max-w-sm mx-auto">
                Completed and failed ForgeAI autonomous executions will appear here for your review and auditing.
              </p>
            </div>
          ) : (
            filteredHistory.map((item) => (
              <div 
                key={item.id} 
                onClick={() => setSelectedItem(item)}
                className="bg-[var(--card)] border border-[var(--border)] hover:border-[var(--primary)]/50 rounded-xl p-5 cursor-pointer transition-all hover:shadow-lg group flex gap-4"
              >
                <div className="pt-1">
                  <div className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider border ${getStatusColor(item.status)}`}>
                    {item.status}
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-[var(--foreground)] font-medium mb-1 truncate">
                    {item.task}
                  </h3>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[var(--muted)]">
                    <span className="flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      {new Date(item.timestamp).toLocaleString()}
                    </span>
                    <span className="flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {item.duration.toFixed(1)}s
                    </span>
                    <span className="flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      {item.changedFilesCount} files
                    </span>
                    {item.gitCommit && (
                      <span className="flex items-center gap-1 font-mono">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
                        </svg>
                        {item.gitCommit.hash.substring(0, 7)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center text-[var(--muted)] group-hover:text-[var(--primary)] transition-colors pl-4">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </div>
            ))
          )}

        </div>
      </main>
    </div>
  );
};

export default HistoryView;
