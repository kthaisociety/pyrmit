'use client';

import { useState } from 'react';
import { ArrowLeft, LogOut, Trash2, Check, X } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { useLanguage } from '@/lib/i18n';
import ApiKeySettings from '@/components/ApiKeySettings';
import LanguageSwitch from '@/components/LanguageSwitch';
import UserRoleSettings, { ROLE_LABEL } from '@/components/UserRoleSettings';
import { isOwner, type CurrentUser } from '@/lib/roles';

type User = CurrentUser;

// The grouped-card look shared by every section of the view (ApiKeySettings and UserRoleSettings repeat CARD and
// HEADING): a white rounded card on the light grey page (header and page one colour), as in iOS settings and the place card.
const CARD = 'rounded-xl bg-white shadow-sm ring-1 ring-black/5 dark:bg-zinc-800 dark:ring-white/10';
const HEADING = 'px-1 text-[13px] font-semibold text-zinc-500 dark:text-zinc-400';
const INPUT = 'px-3 py-2 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500 outline-none text-sm';
const PRIMARY = 'shrink-0 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2';

interface SettingsProps {
  user: User;
  onBack: () => void;
  onLogout: () => void;
  logoutLoading: boolean;
  logoutError: string;
  onUserUpdated: (user: User) => void;
  onAllChatsCleared: () => void;
}

export default function Settings({ user, onBack, onLogout, logoutLoading, logoutError, onUserUpdated, onAllChatsCleared }: SettingsProps) {
  const { t } = useLanguage();
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
      const res = await authFetch('/api/auth/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || t('settings.updateNameFailed'));
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
      const res = await authFetch('/api/auth/password', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || t('settings.changePasswordFailed'));
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
      const res = await authFetch('/api/sessions', {
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
    <div className="flex flex-col h-full w-full bg-zinc-50 dark:bg-zinc-900">
      {/* Header */}
      <div className="px-6 py-3 flex items-center gap-3">
        <button
          onClick={onBack}
          className="p-1.5 rounded-lg hover:bg-zinc-200/70 dark:hover:bg-zinc-800 transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-lg font-semibold">{t('settings.title')}</h1>
      </div>

      {/* Content: iOS-style grouped cards, a small grey heading above each */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-lg mx-auto px-4 py-5 space-y-5">

          {/* Language */}
          <section className="space-y-1.5">
            <h2 className={HEADING}>{t('settings.language')}</h2>
            <div className={`${CARD} flex items-center justify-between gap-3 px-4 py-3`}>
              <span className="text-sm">{t('language.switch')}</span>
              <LanguageSwitch />
            </div>
          </section>

          {/* Account Info */}
          <section className="space-y-1.5">
            <h2 className={HEADING}>{t('settings.account')}</h2>
            <div className={`${CARD} flex items-center gap-3 px-4 py-3`}>
              <div className="w-11 h-11 shrink-0 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-300 font-bold">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="font-medium truncate">{user.name}</p>
                <p className="text-sm text-zinc-500 dark:text-zinc-400 truncate">{user.email}</p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t('settings.role')}: {t(ROLE_LABEL[user.role ?? 'user'])}
                </p>
              </div>
            </div>
          </section>

          {/* Change Name */}
          <section className="space-y-1.5">
            <h2 className={HEADING}>{t('settings.displayName')}</h2>
            <form onSubmit={handleUpdateName} className={`${CARD} p-3 space-y-2`}>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className={`${INPUT} flex-1 min-w-0`}
                  minLength={2}
                  maxLength={100}
                />
                <button
                  type="submit"
                  disabled={nameLoading || name.trim() === user.name || name.trim().length < 2}
                  className={PRIMARY}
                >
                  {nameSuccess ? (
                    <>
                      <Check size={14} />
                      {t('settings.saved')}
                    </>
                  ) : nameLoading ? t('settings.saving') : t('settings.updateName')}
                </button>
              </div>
              {nameError && (
                <p className="text-red-500 text-sm">{nameError}</p>
              )}
            </form>
          </section>

          {/* Change Password */}
          <section className="space-y-1.5">
            <h2 className={HEADING}>{t('settings.changePasswordHeading')}</h2>
            <form onSubmit={handleChangePassword} className={`${CARD} p-3 space-y-2`}>
              <label className="block">
                <span className="block text-xs text-zinc-500 dark:text-zinc-400 mb-1">{t('settings.currentPassword')}</span>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className={`${INPUT} w-full`}
                  minLength={8}
                />
              </label>
              <label className="block">
                <span className="block text-xs text-zinc-500 dark:text-zinc-400 mb-1">{t('settings.newPassword')}</span>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className={`${INPUT} w-full`}
                  minLength={8}
                />
              </label>
              {passwordError && (
                <p className="text-red-500 text-sm">{passwordError}</p>
              )}
              <div className="flex justify-end pt-1">
                <button
                  type="submit"
                  disabled={passwordLoading || !currentPassword || !newPassword || newPassword.length < 8}
                  className={PRIMARY}
                >
                  {passwordSuccess ? (
                    <>
                      <Check size={14} />
                      {t('settings.changed')}
                    </>
                  ) : passwordLoading ? t('settings.changing') : t('settings.changePassword')}
                </button>
              </div>
            </form>
          </section>

          {/* Own OpenRouter key (issue #108) */}
          <ApiKeySettings />

          {isOwner(user) && <UserRoleSettings currentUserId={user.id} />}

          {/* Danger Zone */}
          <section className="space-y-1.5">
            <h2 className="px-1 text-[13px] font-semibold text-red-500">{t('settings.dangerZone')}</h2>
            <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-red-200 dark:bg-zinc-800 dark:ring-red-900/70 divide-y divide-zinc-200/70 dark:divide-white/10">
              {/* Clear All Chats */}
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">{t('settings.clearAllChats')}</p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">{t('settings.clearAllChatsHint')}</p>
                </div>
                {confirmClear ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleClearAllChats}
                      disabled={clearLoading}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50"
                    >
                      {clearLoading ? t('settings.clearing') : t('settings.confirm')}
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
                    className="shrink-0 px-3 py-1.5 border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 text-xs font-medium rounded-lg hover:bg-red-50 dark:hover:bg-red-950 transition-colors"
                  >
                    <span className="flex items-center gap-1.5">
                      <Trash2 size={12} />
                      {t('settings.clearAll')}
                    </span>
                  </button>
                )}
              </div>

              {/* Sign Out */}
              <div className="px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{t('settings.signOutHeading')}</p>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">{t('settings.signOutHint')}</p>
                  </div>
                  <button
                    onClick={onLogout}
                    disabled={logoutLoading}
                    className="shrink-0 px-3 py-1.5 border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 text-xs font-medium rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
                  >
                    <span className="flex items-center gap-1.5">
                      <LogOut size={12} />
                      {logoutLoading ? t('settings.signingOut') : t('settings.signOut')}
                    </span>
                  </button>
                </div>
                {logoutError && <p role="alert" className="mt-2 text-xs text-red-600">{logoutError}</p>}
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  );
}
