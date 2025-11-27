'use client';

import Chat from '@/components/Chat';
import { MessageSquare, Plus, Settings, User } from 'lucide-react';

export default function Home() {
  return (
    <div className="flex h-screen w-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-[260px] bg-zinc-50 dark:bg-black border-r border-zinc-200 dark:border-zinc-800 flex flex-col flex-shrink-0">
        <div className="p-3">
          <button className="w-full flex items-center gap-2 px-3 py-2 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors text-sm font-medium shadow-sm">
            <Plus size={16} />
            <span>New Chat</span>
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto px-3 py-2">
          <div className="mb-4">
            <h3 className="text-xs font-semibold text-zinc-500 dark:text-zinc-500 px-2 mb-2">Today</h3>
            <div className="space-y-1">
              <button className="w-full text-left px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg flex items-center gap-2 transition-colors truncate">
                <span className="truncate">Building Permit Requirements</span>
              </button>
              <button className="w-full text-left px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg flex items-center gap-2 transition-colors truncate">
                <span className="truncate">Zoning Laws in CA</span>
              </button>
            </div>
          </div>
        </div>

        <div className="p-3 border-t border-zinc-200 dark:border-zinc-800">
          <button className="w-full flex items-center gap-2 px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg transition-colors">
            <User size={16} />
            <span>User Account</span>
          </button>
          <button className="w-full flex items-center gap-2 px-2 py-2 text-sm hover:bg-zinc-200 dark:hover:bg-zinc-900 rounded-lg transition-colors">
            <Settings size={16} />
            <span>Settings</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col h-full relative min-w-0">
        <Chat />
      </main>
    </div>
  );
}

