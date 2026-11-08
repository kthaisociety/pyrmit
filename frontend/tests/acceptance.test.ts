// Acceptance tests of #75: the page in Swedish or English, remembered per browser, with the shared glossary.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, type ReactNode, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AuthPage from '@/app/(protected)/auth/page';
import DevAccessForm from '@/app/dev-access/dev-access-form';
import LanguageSwitch from '@/components/LanguageSwitch';
import PlacePanel from '@/components/place/PlacePanel';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import Sidebar from '@/components/Sidebar';
import Term from '@/components/Term';
import { LanguageProvider } from '@/lib/i18n';
import type { Pin } from '@/lib/place';

import { kungsangen } from './mocks/place';
import { server } from './mocks/server';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock('next/image', () => ({ default: (props: { alt: string }) => createElement('img', { alt: props.alt }) }));
vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement('button', { onClick: () => props.onMapClick({ lat: 59.8505, lon: 17.641 }) }, 'Click Kungsängen'),
}));

const GATE_HEADING = 'Enter the shared password';

function browserLanguages(languages: string[]) {
  Object.defineProperty(window.navigator, 'languages', { value: languages, configurable: true });
  Object.defineProperty(window.navigator, 'language', { value: languages[0], configurable: true });
}

function inProvider(...children: ReactNode[]) {
  return render(createElement(LanguageProvider, null, ...children));
}

function gatePage() {
  return inProvider(createElement(DevAccessForm, { nextPath: '/' }));
}

const SIDEBAR_PROPS = {
  currentSessionId: null, onSelectSession: vi.fn(), onNewChat: vi.fn(), refreshTrigger: 0,
  user: { id: 'u1', name: 'anna', email: 'anna@example.com' }, onOpenSettings: vi.fn(), onOpenDatabase: vi.fn(),
  onOpenBenchmark: vi.fn(), onOpenPipeline: vi.fn(),
};

async function openKungsangen() {
  inProvider(createElement(PanelHarness));
  await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
  await screen.findByText('Uppsala Kungsängen 7:8');
}

function PanelHarness() {
  const [pin, setPin] = useState<Pin | null>(null);
  return createElement('div', null, createElement(LanguageSwitch),
                       createElement(PlacePanel, { pin, onPinChange: setPin, onClose: () => undefined }));
}

afterEach(() => {
  browserLanguages(['en-US']);
  document.documentElement.lang = '';
});

describe('first visit', () => {
  it('shows the page in Swedish when the browser prefers Swedish', async () => {
    /** A first-time visitor whose browser prefers sv-SE gets the page in Swedish. */
    browserLanguages(['sv-SE', 'en-US']);
    gatePage();

    await waitFor(() => expect(document.documentElement.lang).toBe('sv'));
    expect(screen.queryByText(GATE_HEADING)).not.toBeInTheDocument();
  });

  it('shows the page in English when the browser prefers another language', async () => {
    /** A first-time visitor whose browser prefers German gets the page in English. */
    browserLanguages(['de-DE', 'sv-SE']);
    gatePage();

    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(screen.getByText(GATE_HEADING)).toBeInTheDocument();
  });
});

describe('language switch', () => {
  it('switches the page to Swedish', async () => {
    /** Choosing Svenska turns the page's texts Swedish. */
    gatePage();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(document.documentElement.lang).toBe('sv');
    expect(screen.queryByText(GATE_HEADING)).not.toBeInTheDocument();
  });

  it('marks the current language as pressed', async () => {
    /** The button of the current language is pressed and the other is not. */
    gatePage();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(screen.getByRole('button', { name: 'Svenska' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('remembers the choice across a reload', async () => {
    /** After choosing Svenska, a new page load in an English browser still shows Swedish. */
    const first = gatePage();
    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));
    first.unmount();
    document.documentElement.lang = '';

    gatePage();

    await waitFor(() => expect(document.documentElement.lang).toBe('sv'));
  });

  it('is on the access gate page', () => {
    /** The access gate form carries the language switch. */
    inProvider(createElement(DevAccessForm, { nextPath: '/' }));

    expect(screen.getByRole('button', { name: 'Svenska' })).toBeInTheDocument();
  });

  it('is on the sign-in page', () => {
    /** The sign-in page carries the language switch. */
    inProvider(createElement(AuthPage));

    expect(screen.getByRole('button', { name: 'Svenska' })).toBeInTheDocument();
  });

  it('is in the sidebar of the app', () => {
    /** The app's sidebar carries the language switch. */
    inProvider(createElement(Sidebar, SIDEBAR_PROPS));

    expect(screen.getByRole('button', { name: 'Svenska' })).toBeInTheDocument();
  });

  it('switches the sidebar to Swedish', async () => {
    /** Choosing Svenska in the sidebar turns its texts Swedish. */
    server.use(http.get('*/api/sessions', () => HttpResponse.json([])));
    inProvider(createElement(Sidebar, SIDEBAR_PROPS));

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(await screen.findByRole('button', { name: 'Ny chatt' })).toBeInTheDocument();
  });

  it('switches the place card to Swedish', async () => {
    /** Choosing Svenska with a place card open turns the card's texts Swedish. */
    await openKungsangen();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(await screen.findByText(/Troliga tillstånd/)).toBeInTheDocument();
  });

  it('fetches the place card again in the new language', async () => {
    /** Switching to Svenska with a place card open fetches its profile again with language=sv. */
    const languages: (string | null)[] = [];
    server.use(http.get('*/api/place/profile', ({ request }) => {
      languages.push(new URL(request.url).searchParams.get('language'));
      return HttpResponse.json(kungsangen);
    }));
    await openKungsangen();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    await waitFor(() => expect(languages).toEqual(['en', 'sv']));
  });
});

describe('glossary terms', () => {
  it('in English, a glossary term keeps its Swedish form with its explanation as tooltip', async () => {
    /** In English "bygglov" shows as is, titled with its glossary explanation. */
    inProvider(createElement(Term, { term: 'bygglov' }));

    await waitFor(() => expect(screen.getByText('bygglov')).toHaveAttribute('title', 'building permit'));
  });

  it('in English, the place card shows detaljplan with its explanation as tooltip', async () => {
    /** The place card's detaljplan pill keeps "detaljplan" in Swedish, titled with its glossary explanation. */
    await openKungsangen();

    const pill = screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === 'Inside a detaljplan');

    await waitFor(() => expect(within(pill).getByText('detaljplan')).toHaveAttribute('title', 'detailed development plan'));
  });

  it('matches a capitalised term to its glossary entry', async () => {
    /** "Bygglov" with a capital letter finds the lower-case entry. */
    inProvider(createElement(Term, { term: 'Bygglov' }));

    await waitFor(() => expect(screen.getByText('Bygglov')).toHaveAttribute('title', 'building permit'));
  });

  it('in Swedish, a glossary term has no explanation', async () => {
    /** In Swedish "bygglov" shows without a title, though the glossary has it. */
    let fetched = false;
    server.use(http.get('*/api/glossary', () => {
      fetched = true;
      return HttpResponse.json({ bygglov: 'building permit' });
    }));
    browserLanguages(['sv-SE']);
    inProvider(createElement(Term, { term: 'bygglov' }));

    await waitFor(() => expect(fetched).toBe(true));
    expect(screen.getByText('bygglov')).not.toHaveAttribute('title');
  });

  it('a term with no glossary entry stays in Swedish without explanation', async () => {
    /** In English a term missing from the glossary shows as is, with no title. */
    let fetched = false;
    server.use(http.get('*/api/glossary', () => {
      fetched = true;
      return HttpResponse.json({ bygglov: 'building permit' });
    }));
    inProvider(createElement(Term, { term: 'tomträtt' }));

    await waitFor(() => expect(fetched).toBe(true));
    expect(screen.getByText('tomträtt')).not.toHaveAttribute('title');
  });

  it('shows the term without explanation when the glossary cannot be fetched', async () => {
    /** A failed glossary fetch leaves terms without a title and shows no error. */
    let fetched = false;
    server.use(http.get('*/api/glossary', () => {
      fetched = true;
      return new HttpResponse(null, { status: 500 });
    }));
    inProvider(createElement(Term, { term: 'bygglov' }));

    await waitFor(() => expect(fetched).toBe(true));
    expect(screen.getByText('bygglov')).not.toHaveAttribute('title');
  });

  it('fetches the glossary once per page load', async () => {
    /** Two terms on one page share one glossary request. */
    let requests = 0;
    server.use(http.get('*/api/glossary', () => {
      requests += 1;
      return HttpResponse.json({ bygglov: 'building permit', detaljplan: 'detailed development plan' });
    }));
    inProvider(createElement(Term, { term: 'bygglov' }), createElement(Term, { term: 'detaljplan' }));

    await waitFor(() => expect(screen.getByText('detaljplan')).toHaveAttribute('title', 'detailed development plan'));
    expect(requests).toBe(1);
  });
});
