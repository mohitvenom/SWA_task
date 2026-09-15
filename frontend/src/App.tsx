import { useState } from 'react';
import Sidebar, { type ViewType } from './components/Sidebar';
import MainContent from './components/MainContent';
import HistoryView from './components/HistoryView';
import WorkspaceView from './components/WorkspaceView';
import SettingsView from './components/SettingsView';

function App() {
  const [currentView, setCurrentView] = useState<ViewType>('dashboard');
  const [initialTask, setInitialTask] = useState<{task: string, workspace: string} | null>(null);

  const handleReopenTask = (task: string, workspace: string) => {
    setInitialTask({ task, workspace });
    setCurrentView('dashboard');
  };

  const getActiveWorkspace = () => {
    return initialTask?.workspace || 'c:/Users/U73/Desktop/P_P/SWA_task';
  };

  return (
    <div className="flex h-screen w-full bg-[var(--background)] text-[var(--foreground)] overflow-hidden font-sans">
      <Sidebar currentView={currentView} setCurrentView={setCurrentView} />
      {currentView === 'dashboard' && (
        <MainContent initialTask={initialTask} />
      )}
      {currentView === 'history' && (
        <HistoryView onReopenTask={handleReopenTask} />
      )}
      {currentView === 'workspace' && (
        <WorkspaceView workspaceRoot={getActiveWorkspace()} />
      )}
      {currentView === 'settings' && (
        <SettingsView />
      )}
    </div>
  );
}

export default App;
