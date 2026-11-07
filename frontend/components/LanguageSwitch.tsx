'use client';

// The page language switch (#75): two buttons, "Svenska" and "English", each named in its own language, the
// current one pressed (aria-pressed). Clicking one sets the language through useLanguage. Needs a LanguageProvider.
import type { ReactNode } from 'react';

import { type Language, useLanguage } from '@/lib/i18n';

const OPTIONS: { language: Language; label: string; short: string }[] = [
  { language: 'sv', label: 'Svenska', short: 'SV' },
  { language: 'en', label: 'English', short: 'EN' },
];

export default function LanguageSwitch(): ReactNode {
  const { language, setLanguage, t } = useLanguage();
  return (
    <div role="group" aria-label={t('language.switch')}
         className={`inline-flex overflow-hidden rounded-lg border border-zinc-300 text-xs font-medium dark:border-zinc-700`}>
      {OPTIONS.map((option) => (
        <button key={option.language} type="button" aria-label={option.label} lang={option.language}
                aria-pressed={language === option.language} onClick={() => setLanguage(option.language)}
                className={`px-2 py-1 ${language === option.language
                  ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                  : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800'}`}>
          {option.short}
        </button>
      ))}
    </div>
  );
}
