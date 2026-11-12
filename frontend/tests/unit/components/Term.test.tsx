// Unit tests for components/Term.tsx: a Swedish domain term, with its glossary explanation as tooltip in English.
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import Term from '@/components/Term';
import { LanguageProvider } from '@/lib/i18n';

import { server } from '../../mocks/server';

function glossaryFetched(response: () => Response): () => boolean {
  let fetched = false;
  server.use(http.get('*/api/glossary', () => {
    fetched = true;
    return response();
  }));
  return () => fetched;
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'languages', { value: ['en-US'], configurable: true });
});

describe('Term', () => {
  it('in English keeps the Swedish term with its explanation as tooltip', async () => {
    /** In English "bygglov" shows as is, titled with its glossary explanation. */
    render(<Term term="bygglov" />, { wrapper: LanguageProvider });

    await waitFor(() => expect(screen.getByText('bygglov')).toHaveAttribute('title', 'building permit'));
  });

  it('matches a capitalised term to its glossary entry', async () => {
    /** "Bygglov" with a capital letter finds the lower-case entry. */
    render(<Term term="Bygglov" />, { wrapper: LanguageProvider });

    await waitFor(() => expect(screen.getByText('Bygglov')).toHaveAttribute('title', 'building permit'));
  });

  it('in Swedish has no explanation', async () => {
    /** In Swedish "bygglov" shows without a title, though the glossary has it. */
    const fetched = glossaryFetched(() => HttpResponse.json({ bygglov: 'building permit' }));
    Object.defineProperty(window.navigator, 'languages', { value: ['sv-SE'], configurable: true });
    render(<Term term="bygglov" />, { wrapper: LanguageProvider });

    await waitFor(() => expect(fetched()).toBe(true));
    expect(screen.getByText('bygglov')).not.toHaveAttribute('title');
  });

  it('has no explanation for a term missing from the glossary', async () => {
    /** In English a term missing from the glossary shows as is, with no title. */
    const fetched = glossaryFetched(() => HttpResponse.json({ bygglov: 'building permit' }));
    render(<Term term="tomträtt" />, { wrapper: LanguageProvider });

    await waitFor(() => expect(fetched()).toBe(true));
    expect(screen.getByText('tomträtt')).not.toHaveAttribute('title');
  });

  it('has no explanation when the glossary cannot be fetched', async () => {
    /** A failed glossary fetch leaves terms without a title and shows no error. */
    const fetched = glossaryFetched(() => new HttpResponse(null, { status: 500 }));
    render(<Term term="bygglov" />, { wrapper: LanguageProvider });

    await waitFor(() => expect(fetched()).toBe(true));
    expect(screen.getByText('bygglov')).not.toHaveAttribute('title');
  });
});
