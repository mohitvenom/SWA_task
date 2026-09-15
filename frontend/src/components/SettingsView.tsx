import React, { useEffect, useState } from 'react';
import { fetchSettings, type SettingsResponse } from '../api/client';

const SettingsView: React.FC = () => {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const loadSettings = async () => {
      try {
        const data = await fetchSettings();
        if (mounted) setSettings(data);
      } catch (err: any) {
        if (mounted) setError(err.message || 'Failed to load settings');
      } finally {
        if (mounted) setLoading(false);
      }
    };
    loadSettings();
    return () => { mounted = false; };
  }, []);

  if (loading) {
    return (
      <div className="flex-1 p-8 flex items-center justify-center">
        <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 p-8">
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-xl flex items-start gap-3">
          <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
             <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <h3 className="font-bold">Failed to load settings</h3>
            <p className="text-sm mt-1">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--background)] p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div>
          <h1 className="text-3xl font-black text-[var(--foreground)] tracking-tight">System Settings</h1>
          <p className="text-[var(--muted)] mt-2">Read-only view of current backend configuration.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl p-6 shadow-xl">
            <h2 className="text-lg font-bold text-[var(--foreground)] mb-6 flex items-center gap-2">
              <svg className="w-5 h-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
              Execution
            </h2>
            <div className="space-y-4">
              <div className="flex justify-between items-center py-3 border-b border-[var(--border)]">
                <span className="text-sm text-[var(--muted)] font-medium">Autonomous Execution</span>
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${settings?.autonomous_execution_enabled ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                  {settings?.autonomous_execution_enabled ? 'ENABLED' : 'DISABLED'}
                </span>
              </div>
              <div className="flex justify-between items-center py-3 border-b border-[var(--border)]">
                <span className="text-sm text-[var(--muted)] font-medium">Max Duration</span>
                <span className="text-sm font-bold text-[var(--foreground)]">{settings?.max_execution_duration}s</span>
              </div>
              <div className="flex justify-between items-center py-3">
                <span className="text-sm text-[var(--muted)] font-medium">Memory System</span>
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${settings?.memory_enabled ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                  {settings?.memory_enabled ? 'ENABLED' : 'DISABLED'}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl p-6 shadow-xl">
            <h2 className="text-lg font-bold text-[var(--foreground)] mb-6 flex items-center gap-2">
              <svg className="w-5 h-5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              LLM Provider (OmniRoute)
            </h2>
            <div className="space-y-4">
              <div className="flex justify-between items-center py-3 border-b border-[var(--border)]">
                <span className="text-sm text-[var(--muted)] font-medium">Status</span>
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${settings?.llm_provider_configured ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                  {settings?.llm_provider_configured ? 'CONFIGURED' : 'NOT CONFIGURED'}
                </span>
              </div>
              <div className="flex justify-between items-center py-3">
                <span className="text-sm text-[var(--muted)] font-medium">Default Model</span>
                <span className="text-sm font-mono text-[var(--foreground)] px-3 py-1 bg-[var(--input)] rounded">
                  {settings?.llm_default_model || 'None'}
                </span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-6 flex items-start gap-4">
          <svg className="w-6 h-6 text-blue-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <h3 className="font-bold text-[var(--foreground)]">Read-Only Configuration</h3>
            <p className="text-sm text-[var(--muted)] mt-1">
              Configuration must be edited via environment variables (`.env`) directly on the host machine to ensure strict security isolation. Changes require restarting the backend.
            </p>
          </div>
        </div>

      </div>
    </div>
  );
};

export default SettingsView;
