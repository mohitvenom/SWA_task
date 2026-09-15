import React from 'react';

interface WorkspaceViewProps {
  workspaceRoot: string;
}

const WorkspaceView: React.FC<WorkspaceViewProps> = ({ workspaceRoot }) => {
  return (
    <div className="flex-1 overflow-y-auto bg-[var(--background)] p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div>
          <h1 className="text-3xl font-black text-[var(--foreground)] tracking-tight">Active Workspace</h1>
          <p className="text-[var(--muted)] mt-2">The current execution environment context.</p>
        </div>

        <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl p-6 shadow-xl">
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-6 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            Workspace Root
          </h2>
          
          <div className="bg-[var(--input)] border border-[var(--border)] p-4 rounded-lg">
            {workspaceRoot ? (
              <span className="font-mono text-sm text-[var(--foreground)] break-all">{workspaceRoot}</span>
            ) : (
              <span className="text-sm text-[var(--muted)] italic">No workspace currently configured in the dashboard.</span>
            )}
          </div>
        </div>

        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-6 flex items-start gap-4">
          <svg className="w-6 h-6 text-amber-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <h3 className="font-bold text-amber-500">Security Notice</h3>
            <p className="text-sm text-amber-500/80 mt-1 leading-relaxed">
              For security reasons, arbitrary filesystem browsing is disabled. ForgeAI strictly operates within the boundaries of the authorized Git workspace provided above. Any attempts by the autonomous agent to traverse outside this directory are actively blocked by the Sandbox boundary.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default WorkspaceView;
