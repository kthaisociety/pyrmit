// Unit tests for lib/i18n.tsx: the page language, remembered per browser, the shared glossary and fill.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import LanguageSwitch from '@/components/LanguageSwitch';
import Term from '@/components/Term';
import { fill, LanguageProvider, useLanguage } from '@/lib/i18n';

import { server } from '../../mocks/server';

function browserLanguages(languages: string[]) {
  Object.defineProperty(window.navigator, 'languages', { value: languages, configurable: true });
  Object.defineProperty(window.navigator, 'language', { value: languages[0], configurable: true });
}

function NewChatLabel() {
  return <span>{useLanguage().t('sidebar.newChat')}</span>;
}

afterEach(() => {
  browserLanguages(['en-US']);
  document.documentElement.lang = '';
});

describe('LanguageProvider', () => {
  it('starts in Swedish when the browser prefers Swedish', async () => {
    /** A first-time visitor whose browser prefers sv-SE gets the page in Swedish. */
    browserLanguages(['sv-SE', 'en-US']);
    render(<LanguageProvider><NewChatLabel /></LanguageProvider>);

    await waitFor(() => expect(document.documentElement.lang).toBe('sv'));
  });

  it('starts in English when the browser prefers another language', async () => {
    /** A first-time visitor whose browser prefers German gets the page in English. */
    browserLanguages(['de-DE', 'sv-SE']);
    render(<LanguageProvider><NewChatLabel /></LanguageProvider>);

    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
  });

  it('gives the texts of the current language', async () => {
    /** In Swedish, t() returns the Swedish text of a key. */
    browserLanguages(['sv-SE']);
    render(<LanguageProvider><NewChatLabel /></LanguageProvider>);

    expect(await screen.findByText('Ny chatt')).toBeInTheDocument();
  });

  it('remembers the choice across a reload', async () => {
    /** After choosing Svenska, a new page load in an English browser still shows Swedish. */
    const first = render(<LanguageProvider><LanguageSwitch /></LanguageProvider>);
    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));
    first.unmount();
    document.documentElement.lang = '';

    render(<LanguageProvider><LanguageSwitch /></LanguageProvider>);

    await waitFor(() => expect(document.documentElement.lang).toBe('sv'));
  });

  it('fetches the glossary once per page load', async () => {
    /** Two terms on one page share one glossary request. */
    let requests = 0;
    server.use(http.get('*/api/glossary', () => {
      requests += 1;
      return HttpResponse.json({ bygglov: 'building permit', detaljplan: 'detailed development plan' });
    }));
    render(<LanguageProvider><Term term="bygglov" /><Term term="detaljplan" /></LanguageProvider>);

    await waitFor(() => expect(screen.getByText('detaljplan')).toHaveAttribute('title', 'detailed development plan'));
    expect(requests).toBe(1);
  });
});

describe('useLanguage', () => {
  it('throws outside a LanguageProvider', () => {
    /** A component using the language without a provider fails loudly. */
    expect(() => render(<NewChatLabel />)).toThrow('useLanguage needs a LanguageProvider');
  });
});

describe('fill', () => {
  it('replaces a placeholder with its value', () => {
    /** "{count}" becomes the given count. */
    expect(fill('{count} plans', { count: '3' })).toBe('3 plans');
  });

  it('leaves a placeholder with no value as it is', () => {
    /** A placeholder missing from the values stays in the text. */
    expect(fill('{count} of {total}', { count: '3' })).toBe('3 of {total}');
  });

  it('replaces only the first occurrence of a placeholder', () => {
    /** A placeholder written twice is filled once, at its first occurrence. */
    expect(fill('{x} and {x}', { x: '1' })).toBe('1 and {x}');
  });
});
