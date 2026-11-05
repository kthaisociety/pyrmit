'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Chat from '@/components/Chat';
import Sidebar from '@/components/Sidebar';
import Settings from '@/components/Settings';
import { authFetch, clearAccessToken, getStoredAccessToken } from '@/lib/auth';

interface User {
  id: string;
  name: string;
  email: string;
}

export default function Home() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [refreshSidebarTrigger, setRefreshSidebarTrigger] = useState(0);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [logoutLoading, setLogoutLoading] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const router = useRouter();

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
      setLogoutError('Could not sign out. Please try again.');
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
        <p role="alert">Could not load your account.</p>
        <button onClick={() => window.location.reload()} className="underline">Try again</button>
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
      <Sidebar
        currentSessionId={currentSessionId}
        onSelectSession={(id) => { setCurrentSessionId(id); setShowSettings(false); }}
        onNewChat={() => { setCurrentSessionId(null); setShowSettings(false); }}
        refreshTrigger={refreshSidebarTrigger}
        user={user}
        onOpenSettings={() => setShowSettings(true)}
      />

      <main className="flex-1 flex flex-col h-full relative min-w-0">
        {showSettings && user ? (
          <Settings
            user={user}
            onBack={() => setShowSettings(false)}
            onLogout={handleLogout}
            logoutLoading={logoutLoading}
            logoutError={logoutError}
            onUserUpdated={(updated) => setUser(updated)}
            onAllChatsCleared={handleAllChatsCleared}
          />
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
