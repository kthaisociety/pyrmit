'use client';

import { FormEvent, useState } from 'react';

import LanguageSwitch from '@/components/LanguageSwitch';
import { useLanguage } from '@/lib/i18n';

type DevAccessFormProps = {
  nextPath: string;
};

export default function DevAccessForm({ nextPath }: DevAccessFormProps) {
  const { t } = useLanguage();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await fetch('/api/access-gate/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ password }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || t('gate.denied'));
      }

      // Force a document navigation so the server-side protected layout sees
      // the newly issued httpOnly access-gate cookie on the next request.
      window.location.assign(nextPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('gate.denied'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-950 px-4 text-zinc-50">
      <section className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-900/90 p-8 shadow-2xl shadow-black/30">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-zinc-500">
              {t('gate.eyebrow')}
            </p>
            <LanguageSwitch />
          </div>
          <h1 className="text-3xl font-semibold text-white">{t('gate.title')}</h1>
          <p className="text-sm leading-6 text-zinc-400">{t('gate.body')}</p>
        </div>

        <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-medium text-zinc-200" htmlFor="dev-password">
              {t('gate.password')}
            </label>
            <input
              id="dev-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-2xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-base text-white outline-none transition focus:border-blue-500"
              placeholder={t('gate.placeholder')}
              required
            />
          </div>

          {error ? (
            <p className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-2xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? t('gate.checking') : t('gate.continue')}
          </button>
        </form>
      </section>
    </main>
  );
}
