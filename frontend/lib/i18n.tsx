'use client';

// The page language, Swedish or English (#75): chosen by the visitor, remembered per browser.
import type { ReactNode } from 'react';

import type { MessageKey } from '@/lib/messages';

export type Language = 'sv' | 'en';

// Where the choice is remembered (localStorage)
export const LANGUAGE_STORAGE_KEY = 'pyrmit.language';

export interface LanguageState {
  language: Language;
  // Switches every text, sets <html lang> and remembers the choice under LANGUAGE_STORAGE_KEY
  setLanguage: (language: Language) => void;
  // The text of `key` in the current language (lib/messages.ts)
  t: (key: MessageKey) => string;
}

/**
 * Provides the page language to everything inside it, and the shared glossary to every Term.
 *
 * The language on mount is the remembered choice when LANGUAGE_STORAGE_KEY holds "sv" or "en"; otherwise Swedish
 * when the browser's first preferred language (navigator.languages, else navigator.language) starts with "sv", and
 * English for any other. It keeps <html lang> equal to the language. It fetches GET /api/glossary once per mount;
 * a failed fetch leaves the glossary empty and shows no error.
 */
export function LanguageProvider({ children }: { children: ReactNode }): ReactNode {
  throw new Error('Not implemented');
}

/** The page language and its texts. Outside a LanguageProvider it throws. */
export function useLanguage(): LanguageState {
  throw new Error('Not implemented');
}
