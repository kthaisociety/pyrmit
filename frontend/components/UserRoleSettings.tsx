'use client';

import { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { useLanguage } from '@/lib/i18n';
import { ROLES, type Role } from '@/lib/roles';
import type { MessageKey } from '@/lib/messages';

// Settings section for owners (issue #112): every user and their role, changeable. The backend refuses to remove the
// last owner or an owner set by OWNER_EMAILS (409, its message shown here); those rows are locked in the list too.
export interface UserRow {
  id: string;
  name: string;
  email: string;
  role: Role;
  from_owner_emails: boolean;
}

const ROLE_LABEL: Record<Role, MessageKey> = {
  owner: 'settings.roles.owner',
  developer: 'settings.roles.developer',
  user: 'settings.roles.user',
};

async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return typeof data.detail === 'string' ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

export default function UserRoleSettings({ currentUserId }: { currentUserId: string }) {
  const { t } = useLanguage();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    authFetch('/api/users')
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data: UserRow[] = await res.json();
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setLoadError(t('settings.roles.loadFailed'));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const owners = rows?.filter((row) => row.role === 'owner').length ?? 0;

  const changeRole = async (row: UserRow, role: Role) => {
    if (role === row.role) return;
    setBusyId(row.id);
    setError('');
    try {
      const res = await authFetch(`/api/users/${encodeURIComponent(row.id)}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      if (!res.ok) throw new Error(await errorDetail(res, t('settings.roles.saveFailed')));
      const updated: UserRow = await res.json();
      setRows((prev) => prev?.map((r) => (r.id === updated.id ? updated : r)) ?? null);
    } catch (err: any) {
      setError(err.message || t('settings.roles.saveFailed'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="space-y-1.5">
      <h2 className="px-1 text-[13px] font-semibold text-zinc-500 dark:text-zinc-400">
        {t('settings.roles.heading')}
      </h2>
      <p className="px-1 text-xs text-zinc-500 dark:text-zinc-400">{t('settings.roles.hint')}</p>
      {loadError ? (
        <p role="alert" className="text-red-500 text-sm">{loadError}</p>
      ) : !rows ? (
        <p className="text-sm text-zinc-500">{t('settings.roles.loading')}</p>
      ) : (
        <ul className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5 dark:bg-zinc-800 dark:ring-white/10 divide-y divide-zinc-200/70 dark:divide-white/10">
          {rows.map((row) => {
            const locked = row.role === 'owner' && (row.from_owner_emails || owners <= 1);
            return (
              <li key={row.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">
                    {row.name || row.email}
                    {row.id === currentUserId && (
                      <span className="ml-1.5 text-xs text-zinc-500">({t('settings.roles.you')})</span>
                    )}
                  </p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate">{row.email}</p>
                </div>
                <span className="flex items-center gap-1.5 shrink-0">
                  {locked && (
                    <span
                      className="text-zinc-400"
                      title={row.from_owner_emails ? t('settings.roles.fromEnv') : t('settings.roles.lastOwner')}
                    >
                      <Lock size={12} aria-hidden />
                      <span className="sr-only">
                        {row.from_owner_emails ? t('settings.roles.fromEnv') : t('settings.roles.lastOwner')}
                      </span>
                    </span>
                  )}
                  <select
                    aria-label={`${t('settings.roles.roleOf')} ${row.email}`}
                    value={row.role}
                    disabled={busyId !== null || locked}
                    onChange={(e) => changeRole(row, e.target.value as Role)}
                    className="text-xs px-2 py-1 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 disabled:opacity-60"
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>{t(ROLE_LABEL[role])}</option>
                    ))}
                  </select>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {error && <p role="alert" className="text-red-500 text-sm mt-2">{error}</p>}
    </section>
  );
}

export { ROLE_LABEL };
