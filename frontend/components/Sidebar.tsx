'use client';

import { useState, useEffect } from 'react';
import { Plus, Settings, User, MessageSquare } from 'lucide-react';

interface ChatSession {
  id: string;
  title: string | null;
  created_at: string;
}

interface User {
  id: string;
  name: string;
  email: string;
}

interface SidebarProps {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  refreshTrigger: number;
  user: User | null;
  onLogout: () => void;
}

export default function Sidebar({ currentSessionId, onSelectSession, onNewChat, refreshTrigger, user, onLogout }: SidebarProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetch(`${API_URL}/api/sessions`, { credentials: 'include' })
      .then((res) => res.json())
      .then((data) => setSessions(data))
      .catch((err) => console.error('Failed to fetch sessions', err));
  }, [API_URL, refreshTrigger]);

  return (
    <aside className="w-[260px] bg-zinc-50 dark:bg-black border-r border-zinc-200 dark:border-zinc-800 flex flex-col flex-shrink-0">
      <div className="p-3">
        <button 
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors text-sm font-medium shadow-sm"
        >
          <Plus size={16} />
          <span>New Chat</span>
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto px-3 py-2">
        <div className="mb-4">
          <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-500 px-2 mb-2">History</h3>
          <div className="space-y-1">
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`w-full text-left px-2 py-2 text-sm rounded-lg flex items-center gap-2 transition-colors truncate ${
                  currentSessionId === session.id 
                    ? 'bg-zinc-200 dark:bg-zinc-800 font-medium' 
                    : 'hover:bg-zinc-200 dark:hover:bg-zinc-900'
                }`}
              >
                <MessageSquare size={14} className="opacity-50 flex-shrink-0" />
                <span className="truncate">{session.title || 'New Chat'}</span>
              </button>
            ))}
            {sessions.length === 0 && (
              <div className="px-2 py-4 text-xs text-zinc-400 text-center">
                No chat history
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="p-3 border-t border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-2 px-2 py-2 mb-2">
          <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-300 font-bold text-xs">
            {user?.name?.charAt(0).toUpperCase() || 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name}</p>
            <p className="text-xs text-zinc-500 truncate">{user?.email}</p>
          </div>
        </div>
        <button 
          onClick={onLogout}
          className="w-full flex items-center gap-2 px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg transition-colors text-zinc-700 dark:text-zinc-300"
        >
          <Settings size={16} />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
