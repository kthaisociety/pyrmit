'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Chat from '@/components/Chat';
import Sidebar from '@/components/Sidebar';
import Settings from '@/components/Settings';
import DatabaseBrowser from '@/components/DatabaseBrowser';
import BenchmarkBrowser from '@/components/BenchmarkBrowser';
import PipelineBrowser from '@/components/PipelineBrowser';
import SidebarToggle from '@/components/SidebarToggle';
import { authFetch, clearAccessToken, getStoredAccessToken } from '@/lib/auth';
import { useLanguage } from '@/lib/i18n';
import { isStaff, type CurrentUser } from '@/lib/roles';

type User = CurrentUser; // with its role (issue #112)

export default function Home() {
  const { t } = useLanguage();
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [refreshSidebarTrigger, setRefreshSidebarTrigger] = useState(0);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'chat' | 'settings' | 'database' | 'benchmark' | 'pipeline'>('chat');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [logoutLoading, setLogoutLoading] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const router = useRouter();

  // The sidebar stays as the user left it (a per-browser convenience: storage may be unavailable)
  useEffect(() => {
    try {
      if (localStorage.getItem('sidebarOpen') === 'false') setSidebarOpen(false);
    } catch {}
  }, []);

  const toggleSidebar = (open: boolean) => {
    setSidebarOpen(open);
    try {
      localStorage.setItem('sidebarOpen', String(open));
    } catch {}
  };

  useEffect(() => {
    if (!getStoredAccessToken()) {
      router.replace('/auth');
      return;
    }

    authFetch('/api/auth/me')
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error('Not authenticated');
      })
      .then((userData) => {
        setUser(userData);
        setLoading(false);
      })
      .catch(() => {
        setLoadError(true);
        setLoading(false);
      });
  }, [router]);

  const handleSessionCreated = (newSessionId: string) => {
    setCurrentSessionId(newSessionId);
    setRefreshSidebarTrigger(prev => prev + 1);
  };

  const handleLogout = async () => {
    if (logoutLoading) return;
    setLogoutLoading(true);
    setLogoutError('');
    try {
      const response = await authFetch('/api/auth/signout', { method: 'POST' });
      if (response.status === 401) return; // authFetch handles session expiry and the access gate.
      if (!response.ok) throw new Error('Sign out failed');
      clearAccessToken();
      router.replace('/auth');
    } catch {
      setLogoutError(t('chat.signOutFailed'));
    } finally {
      setLogoutLoading(false);
    }
  };

  const handleAllChatsCleared = () => {
    setCurrentSessionId(null);
    setRefreshSidebarTrigger(prev => prev + 1);
  };

  if (loadError) {
    return (
      <div className="h-screen flex flex-col items-center justify-center gap-3">
        <p role="alert">{t('chat.loadAccountFailed')}</p>
        <button onClick={() => window.location.reload()} className="underline">{t('chat.tryAgain')}</button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-white dark:bg-zinc-900">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 overflow-hidden">
      {sidebarOpen && <Sidebar
        onClose={() => toggleSidebar(false)}
        currentSessionId={currentSessionId}
        onSelectSession={(id) => { setCurrentSessionId(id); setView('chat'); }}
        onNewChat={() => { setCurrentSessionId(null); setView('chat'); }}
        refreshTrigger={refreshSidebarTrigger}
        user={user}
        onOpenSettings={() => setView('settings')}
        onOpenDatabase={() => setView('database')}
        onOpenBenchmark={() => setView('benchmark')}
        onOpenPipeline={() => setView('pipeline')}
      />}

      <main className="flex-1 flex flex-col h-full relative min-w-0">
        {!sidebarOpen && (
          <SidebarToggle open={false} onClick={() => toggleSidebar(true)} className="absolute left-3 top-3 z-30" />
        )}
        {view === 'settings' && user ? (
          <Settings
            user={user}
            onBack={() => setView('chat')}
            onLogout={handleLogout}
            logoutLoading={logoutLoading}
            logoutError={logoutError}
            onUserUpdated={(updated) => setUser(updated)}
            onAllChatsCleared={handleAllChatsCleared}
          />
        ) : view === 'database' ? (
          <DatabaseBrowser onBack={() => setView('chat')} />
        ) : view === 'benchmark' ? (
          <BenchmarkBrowser onBack={() => setView('chat')} canRun={isStaff(user)} />
        ) : view === 'pipeline' ? (
          <PipelineBrowser onBack={() => setView('chat')} />
        ) : (
          <Chat
            sessionId={currentSessionId}
            onSessionCreated={handleSessionCreated}
            user={user}
          />
        )}
      </main>
    </div>
  );
}
