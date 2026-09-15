import React from 'react';
import type { ExecutionEvent } from '../api/client';

export interface ExecutionWorkflowProps {
  executionState: 'idle' | 'executing' | 'completed' | 'failed';
  resultStatus?: string;
  liveEvents?: ExecutionEvent[];
}

const WORKFLOW_STEPS = [
  'RECEIVED',
  'UNDERSTANDING',
  'PLANNING',
  'TEST STRATEGY',
  'AUTHORIZING',
  'IMPLEMENTING',
  'VALIDATING',
  'DIAGNOSING',
  'REPAIRING',
  'REVALIDATING',
  'REVIEWING',
  'FINALIZING',
  'COMPLETED'
];

const PHASE_TO_STEP: Record<string, string> = {
  'TASK_INTELLIGENCE': 'UNDERSTANDING',
  'REPOSITORY_INTELLIGENCE': 'UNDERSTANDING',
  'PLANNING': 'PLANNING',
  'TEST_STRATEGY': 'TEST STRATEGY',
  'GIT_TRANSACTION': 'AUTHORIZING',
  'CODING': 'IMPLEMENTING',
  'INSPECTING': 'IMPLEMENTING',
  'IMPLEMENTING': 'IMPLEMENTING',
  'VALIDATING': 'VALIDATING',
  'REPAIRING': 'REPAIRING',
  'REVIEWING': 'REVIEWING',
  'FAST_PATH': 'COMPLETED'
};

const ExecutionWorkflow: React.FC<ExecutionWorkflowProps> = ({ executionState, resultStatus, liveEvents = [] }) => {
  const isExecuting = executionState === 'executing';
  const isFailed = executionState === 'failed' || (resultStatus && resultStatus !== 'COMPLETED');
  const isSuccess = executionState === 'completed' && resultStatus === 'COMPLETED';

  // Determine reached steps from real events
  const reachedSteps = new Set<string>();
  reachedSteps.add('RECEIVED'); // Always reached if not idle
  
  let currentActiveStep = 'RECEIVED';

  liveEvents.forEach(ev => {
    const mapped = PHASE_TO_STEP[ev.phase];
    if (mapped) {
      reachedSteps.add(mapped);
      currentActiveStep = mapped;
    }
  });


  return (
    <div className="w-full bg-[var(--card)] border border-[var(--border)] rounded-xl p-8 shadow-2xl">
      <div className="flex items-center justify-between mb-10">
        <h3 className="text-sm font-bold text-[var(--foreground)] uppercase tracking-wider flex items-center gap-2">
          <svg className="w-5 h-5 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
          </svg>
          Execution Lifecycle
        </h3>
        {isExecuting && (
          <span className="text-xs font-bold text-blue-400 flex items-center gap-2 bg-blue-500/10 px-3 py-1.5 rounded-full border border-blue-500/20 shadow-[0_0_10px_rgba(59,130,246,0.1)]">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping"></span>
            Executing: {currentActiveStep}
          </span>
        )}
        {isFailed && (
          <span className="text-xs font-bold text-red-400 flex items-center gap-2 uppercase tracking-wide px-3 py-1.5 bg-red-500/10 rounded-full border border-red-500/20 shadow-[0_0_10px_rgba(239,68,68,0.1)]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Outcome: {resultStatus || 'FAILED'}
          </span>
        )}
        {isSuccess && (
          <span className="text-xs font-bold text-green-400 flex items-center gap-2 uppercase tracking-wide px-3 py-1.5 bg-green-500/10 rounded-full border border-green-500/20 shadow-[0_0_10px_rgba(34,197,94,0.1)]">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Outcome: COMPLETED
          </span>
        )}
      </div>
      
      <div className="flex items-center justify-between relative max-w-6xl mx-auto px-4">
        {WORKFLOW_STEPS.map((step, index, array) => {
          const isReached = reachedSteps.has(step);
          const isActive = isExecuting && step === currentActiveStep && step !== 'COMPLETED';
          const isErrorStep = isFailed && step === currentActiveStep;

          let dotClass = "w-4 h-4 rounded-full border-2 transition-all duration-500 z-10 bg-[var(--card)] ";
          let labelClass = "text-[9px] font-bold uppercase tracking-wider absolute -bottom-8 whitespace-nowrap transition-colors duration-500 text-center ";
          
          if (executionState === 'idle') {
            dotClass += "border-[var(--border)]";
            labelClass += "text-[var(--muted)]/50";
          } else if (isSuccess) {
            dotClass += "border-green-500 bg-green-500/20 shadow-[0_0_10px_rgba(34,197,94,0.4)]";
            labelClass += "text-green-500/80";
          } else if (isFailed) {
            if (isErrorStep) {
              dotClass += "border-red-500 bg-red-500/20 shadow-[0_0_10px_rgba(239,68,68,0.4)]";
              labelClass += "text-red-500";
            } else if (isReached) {
              dotClass += "border-blue-500/50 bg-[var(--card)]";
              labelClass += "text-blue-500/60";
            } else {
              dotClass += "border-[var(--border)] opacity-30";
              labelClass += "text-[var(--muted)]/30";
            }
          } else if (isExecuting) {
            if (isActive) {
              dotClass += "border-blue-400 bg-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.6)] scale-125";
              labelClass += "text-blue-400 font-black";
            } else if (isReached) {
              dotClass += "border-blue-500/80 bg-blue-500/20 shadow-[0_0_5px_rgba(59,130,246,0.2)]";
              labelClass += "text-blue-500/80";
            } else {
              dotClass += "border-[var(--border)]";
              labelClass += "text-[var(--muted)]/50";
            }
          }

          return (
            <React.Fragment key={step}>
              <div className="flex flex-col items-center group relative">
                <div className="relative flex items-center justify-center">
                  <div className={dotClass}></div>
                  {isActive && (
                    <div className="absolute inset-0 rounded-full border border-blue-400 animate-ping opacity-50 scale-150"></div>
                  )}
                </div>
                <span className={labelClass} style={{ transform: 'translateX(-50%)', left: '50%' }}>
                  {step}
                </span>
              </div>
              
              {index < array.length - 1 && (
                <div className={`flex-1 h-[2px] mx-2 transition-colors duration-500 ${
                  executionState === 'idle' ? 'bg-[var(--border)]/50' :
                  isSuccess ? 'bg-green-500/50 shadow-[0_0_5px_rgba(34,197,94,0.3)]' :
                  isFailed ? (reachedSteps.has(WORKFLOW_STEPS[index + 1]) ? 'bg-blue-500/30' : 'bg-[var(--border)]/30') :
                  isExecuting ? (reachedSteps.has(WORKFLOW_STEPS[index + 1]) ? 'bg-blue-500/60 shadow-[0_0_5px_rgba(59,130,246,0.3)]' : 'bg-[var(--border)]/50') :
                  'bg-[var(--border)]/50'
                }`}></div>
              )}
            </React.Fragment>
          );
        })}
      </div>
      {/* spacer for the absolute positioned labels */}
      <div className="h-8"></div>
    </div>
  );
};

export default ExecutionWorkflow;
