'use client';

// The page language switch: a segmented control of two equal buttons, "Svenska" and "English", each named in its
// own language, the current one pressed (aria-pressed). A pill slides under the chosen one. Clicking one sets the
// language through useLanguage. Needs a LanguageProvider.
import type { ReactNode } from 'react';

import { type Language, useLanguage } from '@/lib/i18n';

const OPTIONS: { language: Language; label: string; short: string }[] = [
  { language: 'sv', label: 'Svenska', short: 'SV' },
  { language: 'en', label: 'English', short: 'EN' },
];

export default function LanguageSwitch(): ReactNode {
  const { language, setLanguage, t } = useLanguage();
  const index = Math.max(0, OPTIONS.findIndex((option) => option.language === language));
  return (
    <div role="group" aria-label={t('language.switch')}
         className="relative inline-grid grid-cols-2 rounded-lg bg-zinc-200/70 p-0.5 text-xs font-medium dark:bg-zinc-700/60">
      <span aria-hidden
            className="absolute inset-y-0.5 left-0.5 w-[calc(50%-2px)] rounded-md bg-white shadow-sm ring-1 ring-black/5 transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] dark:bg-zinc-500 dark:ring-white/10"
            style={{ transform: `translateX(${index * 100}%)` }} />
      {OPTIONS.map((option) => (
        <button key={option.language} type="button" aria-label={option.label} lang={option.language}
                aria-pressed={language === option.language} onClick={() => setLanguage(option.language)}
                className={`relative z-10 w-10 py-1 text-center transition-colors duration-300 ${language === option.language
                  ? 'text-zinc-900 dark:text-white'
                  : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'}`}>
          {option.short}
        </button>
      ))}
    </div>
  );
}
