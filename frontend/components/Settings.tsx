'use client';

import { useState } from 'react';
import { ArrowLeft, LogOut, Trash2, Check, X } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { API_URL } from '@/lib/config';

interface User {
  id: string;
  name: string;
  email: string;
}

interface SettingsProps {
  user: User;
  onBack: () => void;
  onLogout: () => void;
  onUserUpdated: (user: User) => void;
  onAllChatsCleared: () => void;
}

export default function Settings({ user, onBack, onLogout, onUserUpdated, onAllChatsCleared }: SettingsProps) {
  const [name, setName] = useState(user.name);
  const [nameLoading, setNameLoading] = useState(false);
  const [nameSuccess, setNameSuccess] = useState(false);
  const [nameError, setNameError] = useState('');

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordError, setPasswordError] = useState('');

  const [confirmClear, setConfirmClear] = useState(false);
  const [clearLoading, setClearLoading] = useState(false);

  const handleUpdateName = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === user.name) return;

    setNameLoading(true);
    setNameError('');
    setNameSuccess(false);
    try {
      const res = await authFetch(`${API_URL}/api/auth/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to update name');
      }
      const updated = await res.json();
      onUserUpdated({ ...user, name: updated.name });
      setNameSuccess(true);
      setTimeout(() => setNameSuccess(false), 3000);
    } catch (err: any) {
      setNameError(err.message);
    } finally {
      setNameLoading(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword || !newPassword) return;

    setPasswordLoading(true);
    setPasswordError('');
    setPasswordSuccess(false);
    try {
      const res = await authFetch(`${API_URL}/api/auth/password`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to change password');
      }
      setCurrentPassword('');
      setNewPassword('');
      setPasswordSuccess(true);
      setTimeout(() => setPasswordSuccess(false), 3000);
    } catch (err: any) {
      setPasswordError(err.message);
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleClearAllChats = async () => {
    setClearLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/sessions`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to clear chats');
      setConfirmClear(false);
      onAllChatsCleared();
    } catch (err) {
      console.error('Failed to clear chats', err);
    } finally {
      setClearLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 px-6 py-4 flex items-center gap-3">
        <button
          onClick={onBack}
          className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-lg font-semibold">Settings</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-lg mx-auto p-6 space-y-8">

          {/* Account Info */}
          <section>
            <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-4">Account</h2>
            <div className="flex items-center gap-4 p-4 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
              <div className="w-12 h-12 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-300 font-bold text-lg">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div>
                <p className="font-medium">{user.name}</p>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">{user.email}</p>
              </div>
            </div>
          </section>

          {/* Change Name */}
          <section>
            <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-4">Display Name</h2>
            <form onSubmit={handleUpdateName} className="space-y-3">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500 outline-none text-sm"
                minLength={2}
                maxLength={100}
              />
              {nameError && (
                <p className="text-red-500 text-sm">{nameError}</p>
              )}
              <button
                type="submit"
                disabled={nameLoading || name.trim() === user.name || name.trim().length < 2}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {nameSuccess ? (
                  <>
                    <Check size={14} />
                    Saved
                  </>
                ) : nameLoading ? 'Saving...' : 'Update Name'}
              </button>
            </form>
          </section>

          {/* Change Password */}
          <section>
            <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-4">Change Password</h2>
            <form onSubmit={handleChangePassword} className="space-y-3">
              <div>
                <label className="block text-sm text-zinc-600 dark:text-zinc-400 mb-1">Current password</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500 outline-none text-sm"
                  minLength={8}
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-600 dark:text-zinc-400 mb-1">New password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500 outline-none text-sm"
                  minLength={8}
                />
              </div>
              {passwordError && (
                <p className="text-red-500 text-sm">{passwordError}</p>
              )}
              <button
                type="submit"
                disabled={passwordLoading || !currentPassword || !newPassword || newPassword.length < 8}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {passwordSuccess ? (
                  <>
                    <Check size={14} />
                    Changed
                  </>
                ) : passwordLoading ? 'Changing...' : 'Change Password'}
              </button>
            </form>
          </section>

          {/* Danger Zone */}
          <section>
            <h2 className="text-sm font-semibold text-red-500 uppercase tracking-wider mb-4">Danger Zone</h2>
            <div className="space-y-3 p-4 border border-red-200 dark:border-red-900 rounded-xl">
              {/* Clear All Chats */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Clear all chats</p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">Permanently delete all your chat history</p>
                </div>
                {confirmClear ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleClearAllChats}
                      disabled={clearLoading}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50"
                    >
                      {clearLoading ? 'Clearing...' : 'Confirm'}
                    </button>
                    <button
                      onClick={() => setConfirmClear(false)}
                      className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmClear(true)}
                    className="px-3 py-1.5 border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 text-xs font-medium rounded-lg hover:bg-red-50 dark:hover:bg-red-950 transition-colors"
                  >
                    <span className="flex items-center gap-1.5">
                      <Trash2 size={12} />
                      Clear All
                    </span>
                  </button>
                )}
              </div>

              {/* Divider */}
              <div className="border-t border-red-100 dark:border-red-900"></div>

              {/* Sign Out */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Sign out</p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">Sign out of your account on this device</p>
                </div>
                <button
                  onClick={onLogout}
                  className="px-3 py-1.5 border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 text-xs font-medium rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    <LogOut size={12} />
                    Sign Out
                  </span>
                </button>
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  );
}
