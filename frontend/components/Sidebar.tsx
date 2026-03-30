'use client';

import { useState, useEffect, useRef } from 'react';
import { Plus, Settings, MessageSquare, Trash2, Check, X, Pencil } from 'lucide-react';
import { authFetch } from '@/lib/auth';

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
  onOpenSettings: () => void;
}

export default function Sidebar({ currentSessionId, onSelectSession, onNewChat, refreshTrigger, user, onOpenSettings }: SidebarProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    authFetch('/api/sessions')
      .then((res) => res.json())
      .then((data) => setSessions(data))
      .catch((err) => console.error('Failed to fetch sessions', err));
  }, [refreshTrigger]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleDelete = async (sessionId: string) => {
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to delete session');
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      setConfirmingDeleteId(null);
      if (currentSessionId === sessionId) {
        onNewChat();
      }
    } catch (err) {
      console.error('Failed to delete session', err);
    }
  };

  const handleRename = async (sessionId: string) => {
    const trimmed = editTitle.trim();
    if (!trimmed) {
      setEditingId(null);
      return;
    }
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      });
      if (!res.ok) throw new Error('Failed to rename session');
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, title: trimmed } : s))
      );
    } catch (err) {
      console.error('Failed to rename session', err);
    }
    setEditingId(null);
  };

  const startEditing = (session: ChatSession) => {
    setEditingId(session.id);
    setEditTitle(session.title || '');
    setConfirmingDeleteId(null);
  };

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
              <div key={session.id} className="group relative">
                {confirmingDeleteId === session.id ? (
                  // Inline delete confirmation
                  <div className="flex items-center gap-1 px-2 py-2 text-sm rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                    <span className="flex-1 text-red-700 dark:text-red-300 truncate text-xs">Delete this chat?</span>
                    <button
                      onClick={() => handleDelete(session.id)}
                      className="p-1 rounded hover:bg-red-200 dark:hover:bg-red-800 text-red-600 dark:text-red-400"
                      title="Confirm delete"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      onClick={() => setConfirmingDeleteId(null)}
                      className="p-1 rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-500"
                      title="Cancel"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : editingId === session.id ? (
                  // Inline rename input
                  <div className="flex items-center gap-1 px-2 py-1">
                    <input
                      ref={editInputRef}
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleRename(session.id);
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      onBlur={() => handleRename(session.id)}
                      className="flex-1 min-w-0 text-sm px-2 py-1 rounded border border-blue-400 dark:border-blue-600 bg-white dark:bg-zinc-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                ) : (
                  // Normal session row
                  <button
                    onClick={() => onSelectSession(session.id)}
                    onDoubleClick={() => startEditing(session)}
                    className={`w-full text-left px-2 py-2 text-sm rounded-lg flex items-center gap-2 transition-colors ${
                      currentSessionId === session.id
                        ? 'bg-zinc-200 dark:bg-zinc-800 font-medium'
                        : 'hover:bg-zinc-200 dark:hover:bg-zinc-900'
                    }`}
                  >
                    <MessageSquare size={14} className="opacity-50 flex-shrink-0" />
                    <span className="truncate flex-1">{session.title || 'New Chat'}</span>
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <span
                        role="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditing(session);
                        }}
                        className="p-1 rounded hover:bg-zinc-300 dark:hover:bg-zinc-700 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
                        title="Rename"
                      >
                        <Pencil size={12} />
                      </span>
                      <span
                        role="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmingDeleteId(session.id);
                          setEditingId(null);
                        }}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900 text-zinc-400 hover:text-red-500 dark:hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 size={12} />
                      </span>
                    </div>
                  </button>
                )}
              </div>
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
          onClick={onOpenSettings}
          className="w-full flex items-center gap-2 px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg transition-colors text-zinc-700 dark:text-zinc-300"
        >
          <Settings size={16} />
          <span>Settings</span>
        </button>
      </div>
    </aside>
  );
}
