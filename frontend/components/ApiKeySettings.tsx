'use client';

import { useEffect, useState } from 'react';
import { Check, KeyRound, Trash2 } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { fill, useLanguage } from '@/lib/i18n';

// The user's own OpenRouter key (issue #108). The backend never sends the key back, only whether one is set and its
// last 4 characters; `enabled` is false when the server has no API_KEY_ENCRYPTION_KEY (the shared key always pays).
export interface ApiKeyStatus {
  enabled: boolean;
  has_key: boolean;
  last4: string | null;
}

const ENDPOINT = '/api/auth/api-key';

async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return typeof data.detail === 'string' ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

export default function ApiKeySettings() {
  const { t } = useLanguage();
  const [status, setStatus] = useState<ApiKeyStatus | null>(null);
  const [loadError, setLoadError] = useState('');
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authFetch(ENDPOINT)
      .then(async (res) => {
        if (!res.ok) throw new Error();
        const data: ApiKeyStatus = await res.json();
        if (!cancelled) setStatus(data);
      })
      .catch(() => {
        if (!cancelled) setLoadError(t('settings.apiKey.loadFailed'));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = draft.trim();
    if (!key) return;
    setBusy(true);
    setError('');
    try {
      const res = await authFetch(ENDPOINT, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      });
      if (!res.ok) throw new Error(await errorDetail(res, t('settings.apiKey.saveFailed')));
      setStatus(await res.json());
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: any) {
      setError(err.message || t('settings.apiKey.saveFailed'));
    } finally {
      setDraft(''); // the key never stays in the page, saved or not
      setBusy(false);
    }
  };

  const handleRemove = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await authFetch(ENDPOINT, { method: 'DELETE' });
      if (!res.ok) throw new Error(await errorDetail(res, t('settings.apiKey.removeFailed')));
      setStatus(await res.json());
      setEditing(false);
    } catch (err: any) {
      setError(err.message || t('settings.apiKey.removeFailed'));
    } finally {
      setBusy(false);
    }
  };

  const showForm = status?.enabled && (!status.has_key || editing);

  return (
    <section>
      <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-4">
        {t('settings.apiKey.heading')}
      </h2>
      <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">{t('settings.apiKey.hint')}</p>

      {loadError ? (
        <p role="alert" className="text-red-500 text-sm">{loadError}</p>
      ) : !status ? (
        <p className="text-sm text-zinc-500">{t('settings.apiKey.loading')}</p>
      ) : !status.enabled ? (
        <p className="text-sm p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg">{t('settings.apiKey.off')}</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3 p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-lg">
            <span className="flex items-center gap-2 text-sm">
              <KeyRound size={14} className="text-zinc-500" />
              {status.has_key && status.last4
                ? fill(t('settings.apiKey.set'), { last4: status.last4 })
                : t('settings.apiKey.shared')}
              {saved && <Check size={14} className="text-green-600" aria-hidden />}
            </span>
            {status.has_key && !editing && (
              <span className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  disabled={busy}
                  className="px-3 py-1.5 border border-zinc-300 dark:border-zinc-700 text-xs font-medium rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
                >
                  {t('settings.apiKey.replace')}
                </button>
                <button
                  type="button"
                  onClick={handleRemove}
                  disabled={busy}
                  className="px-3 py-1.5 border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 text-xs font-medium rounded-lg hover:bg-red-50 dark:hover:bg-red-950 transition-colors disabled:opacity-50"
                >
                  <span className="flex items-center gap-1.5">
                    <Trash2 size={12} />
                    {t('settings.apiKey.remove')}
                  </span>
                </button>
              </span>
            )}
          </div>

          {showForm && (
            <form onSubmit={handleSave} className="space-y-3">
              <label className="block">
                <span className="block text-sm text-zinc-600 dark:text-zinc-400 mb-1">{t('settings.apiKey.label')}</span>
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={t('settings.apiKey.placeholder')}
                  className="w-full px-4 py-2.5 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500 outline-none text-sm font-mono"
                />
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  disabled={busy || !draft.trim()}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {t('settings.apiKey.save')}
                </button>
                {editing && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(false);
                      setDraft('');
                    }}
                    className="px-4 py-2 text-sm text-zinc-600 dark:text-zinc-400 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    {t('settings.apiKey.cancel')}
                  </button>
                )}
              </div>
            </form>
          )}
          {error && <p role="alert" className="text-red-500 text-sm">{error}</p>}
        </div>
      )}
    </section>
  );
}
