import React, { useState, useEffect } from 'react';
import { checkHealth } from '../api/client';

export type ViewType = 'dashboard' | 'history' | 'workspace' | 'settings';

interface SidebarProps {
  currentView: ViewType;
  setCurrentView: (view: ViewType) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ currentView, setCurrentView }) => {
  const [isConnected, setIsConnected] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    const pollHealth = async () => {
      const healthy = await checkHealth();
      if (mounted) {
        setIsConnected(healthy);
      }
    };
    
    pollHealth();
    const interval = setInterval(pollHealth, 10000); // Check every 10 seconds
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const navItems = [
    { id: 'dashboard', name: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { id: 'new_task', name: 'New Task', icon: 'M12 4v16m8-8H4' },
    { id: 'history', name: 'History', icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' },
    { id: 'workspace', name: 'Workspace', icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10' },
    { id: 'settings', name: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' }
  ];

  return (
    <div className="w-64 bg-[var(--card)] border-r border-[var(--border)] flex flex-col h-screen shadow-2xl relative z-10">
      <div className="h-20 flex items-center px-6 border-b border-[var(--border)] bg-gradient-to-b from-black/20 to-transparent">
        <div className="flex items-center gap-3 text-2xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-xl flex items-center justify-center shadow-[0_0_15px_rgba(59,130,246,0.5)]">
            <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          ForgeAI
        </div>
      </div>
      
      <nav className="flex-1 py-6 px-4 space-y-2 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = (item.id === 'dashboard' || item.id === 'new_task') 
            ? currentView === 'dashboard' 
            : item.id === currentView;
              
          return (
            <button
              key={item.id}
              onClick={() => {
                if (item.id === 'dashboard' || item.id === 'new_task') setCurrentView('dashboard');
                if (item.id === 'history') setCurrentView('history');
                if (item.id === 'workspace') setCurrentView('workspace');
                if (item.id === 'settings') setCurrentView('settings');
              }}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all duration-200 group ${
                isActive
                  ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20 shadow-inner' 
                  : 'text-[var(--muted)] hover:bg-[var(--accent)]/50 hover:text-[var(--foreground)] border border-transparent'
              }`}
            >
              <svg className={`w-5 h-5 transition-transform duration-200 ${isActive ? 'scale-110' : 'group-hover:scale-110'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={isActive ? 2 : 1.5} d={item.icon} />
              </svg>
              {item.name}
              {isActive && (
                <div className="ml-auto w-1.5 h-5 bg-blue-500 rounded-full shadow-[0_0_8px_rgba(59,130,246,0.8)]"></div>
              )}
            </button>
          );
        })}
      </nav>
      
      <div className="p-4 border-t border-[var(--border)] bg-gradient-to-t from-black/20 to-transparent">
        <div className="mb-4 px-4 flex items-center gap-2">
          <div className="relative flex items-center justify-center">
            {isConnected ? (
              <>
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full"></div>
                <div className="absolute w-2.5 h-2.5 bg-green-500 rounded-full animate-ping opacity-75"></div>
              </>
            ) : (
              <div className="w-2.5 h-2.5 bg-red-500 rounded-full"></div>
            )}
          </div>
          <span className="text-xs font-semibold text-[var(--muted)]">
            {isConnected ? 'Backend Connected' : 'Backend Disconnected'}
          </span>
        </div>

        <div className="flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-[var(--accent)]/50 transition-colors cursor-pointer border border-transparent hover:border-[var(--border)] group">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-gray-700 to-gray-900 border border-gray-600 flex items-center justify-center text-sm font-bold shadow-inner group-hover:shadow-[0_0_10px_rgba(255,255,255,0.1)] transition-shadow">
            U
          </div>
          <div className="flex flex-col flex-1">
            <span className="text-sm font-bold text-[var(--foreground)]">User</span>
            <span className="text-xs text-[var(--muted)] font-medium">Pro Plan</span>
          </div>
          <svg className="w-4 h-4 text-[var(--muted)] group-hover:text-[var(--foreground)] transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
          </svg>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;
