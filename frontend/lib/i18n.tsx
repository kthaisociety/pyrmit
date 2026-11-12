'use client';

// The page language, Swedish or English: chosen by the visitor, remembered per browser.
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState,
  useSyncExternalStore } from 'react';

import { authFetch } from '@/lib/auth';
import { en, type MessageKey, sv } from '@/lib/messages';

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
  // English on the server and while hydrating, so hydration matches; the visitor's language right after
  const detected = useSyncExternalStore(subscribeToStorage, initialLanguage, () => 'en' as Language);
  const [chosen, setChosen] = useState<Language | null>(null);
  const language = chosen ?? detected;
  const [glossary, setGlossary] = useState<Record<string, string>>({});

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    let current = true;
    authFetch('/api/glossary')
      .then((response) => (response.ok ? response.json() : {}))
      .then((entries: Record<string, string>) => current && setGlossary(entries))
      .catch(() => undefined); // terms then show without explanation
    return () => {
      current = false;
    };
  }, []);

  const setLanguage = useCallback((next: Language) => {
    setChosen(next);
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // storage blocked: the choice lasts until the page is left
    }
  }, []);

  const state = useMemo<Context>(() => {
    const messages = language === 'sv' ? sv : en;
    return { language, setLanguage, t: (key) => messages[key], glossary };
  }, [language, setLanguage, glossary]);

  return <LanguageContext.Provider value={state}>{children}</LanguageContext.Provider>;
}

/** The page language and its texts. Outside a LanguageProvider it throws. */
export function useLanguage(): LanguageState {
  const { language, setLanguage, t } = useContext(LanguageContext) ?? missingProvider();
  return { language, setLanguage, t };
}

/** The English explanation of a glossary term (lower case), or undefined. For components/Term.tsx. */
export function useGlossaryExplanation(term: string): string | undefined {
  const { glossary } = useContext(LanguageContext) ?? missingProvider();
  return glossary[term.toLowerCase()];
}

/**
 * `text` (a t() result) with each "{name}" placeholder replaced by `values[name]`, in the order `values` lists them.
 * Each placeholder is replaced once, at its first occurrence; a placeholder with no value stays as it is.
 */
export function fill(text: string, values: Record<string, string>): string {
  return Object.entries(values).reduce((filled, [name, value]) => filled.replace(`{${name}}`, value), text);
}

interface Context extends LanguageState {
  glossary: Record<string, string>;
}

const LanguageContext = createContext<Context | null>(null);

function missingProvider(): never {
  throw new Error('useLanguage needs a LanguageProvider');
}

// Another tab choosing a language updates this one too
function subscribeToStorage(onChange: () => void): () => void {
  window.addEventListener('storage', onChange);
  return () => window.removeEventListener('storage', onChange);
}

function initialLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored === 'sv' || stored === 'en') return stored;
  } catch {
    // storage blocked: fall back to the browser's language
  }
  const preferred = window.navigator.languages?.[0] ?? window.navigator.language ?? '';
  return preferred.toLowerCase().startsWith('sv') ? 'sv' : 'en';
}
