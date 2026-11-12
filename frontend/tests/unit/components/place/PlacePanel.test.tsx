// Unit tests for components/place/PlacePanel.tsx. The base map is replaced by a stand-in: WebGL does not run in jsdom.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import LanguageSwitch from '@/components/LanguageSwitch';
import PlacePanel, { REVIEW_PLANS_ZOOM } from '@/components/place/PlacePanel';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import type { BBox, Pin, PlaceSearchResult } from '@/lib/place';
import { LanguageProvider } from '@/lib/i18n';

import { kungsangen, reviewCoverage, reviewPlans } from '../../../mocks/place';
import { server } from '../../../mocks/server';

const NACKA: BBox = [18.0, 59.25, 18.4, 59.4];
const SWEDEN: BBox = [10.5, 55, 24.5, 69.5];

vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement(
      'div',
      { 'data-testid': 'map', 'data-outlines': String(props.outlines.length),
        'data-pin': props.pin ? `${props.pin.lat},${props.pin.lon}` : '',
        'data-proposal': props.proposal ? `${props.proposal.lat},${props.proposal.lon}` : '',
        'data-review': props.review ? 'on' : 'off',
        'data-review-kommuner': props.review?.coverage ? String(props.review.coverage.features.length) : '',
        'data-review-plans': props.review?.plans ? String(props.review.plans.features.length) : '' },
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.8505, lon: 17.641 }) }, 'Click Kungsängen'),
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.88, lon: 17.68 }) }, 'Click Kåbo'),
      createElement('button', { onClick: () => props.onViewChange?.({ bbox: NACKA, zoom: REVIEW_PLANS_ZOOM + 2 }) },
                    'Zoom in on Nacka'),
      createElement('button', { onClick: () => props.onViewChange?.({ bbox: SWEDEN, zoom: REVIEW_PLANS_ZOOM - 4 }) },
                    'Zoom out'),
    ),
}));

function Harness({ start = null }: { start?: Pin | null }) {
  const [pin, setPin] = useState<Pin | null>(start);
  return createElement(PlacePanel, { pin, onPinChange: setPin, onClose: () => undefined });
}

function WithLanguageSwitch() {
  return createElement('div', null, createElement(LanguageSwitch), createElement(Harness));
}

async function openKungsangen() {
  render(createElement(WithLanguageSwitch), { wrapper: LanguageProvider });
  await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
  await screen.findByText('Uppsala Kungsängen 7:8');
}

describe('map panel', () => {
  it('places a pin where the map is clicked and shows the place card', async () => {
    /** A click on the map puts the pin there and the card of that place appears. */
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));

    expect(screen.getByTestId('map')).toHaveAttribute('data-pin', '59.8505,17.641');
    expect(await screen.findByText('Uppsala Kungsängen 7:8')).toBeInTheDocument();
  });

  it('moves the pin on a second click and shows the new place', async () => {
    /** Clicking elsewhere moves the pin and replaces the card. */
    render(createElement(Harness), { wrapper: LanguageProvider });
    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
    await screen.findByText('Uppsala Kungsängen 7:8');

    await userEvent.click(screen.getByRole('button', { name: 'Click Kåbo' }));

    expect(await screen.findByText('Uppsala Kåbo 1:1')).toBeInTheDocument();
    expect(screen.queryByText('Uppsala Kungsängen 7:8')).not.toBeInTheDocument();
  });

  it('outlines the property, its plans and its zones on the map', async () => {
    /** The map gets one outline for the property, each plan and each zone. */
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
    await screen.findByText('Uppsala Kungsängen 7:8');

    const expected = 1 + kungsangen.plans.length + kungsangen.zones.length;
    expect(screen.getByTestId('map')).toHaveAttribute('data-outlines', String(expected));
  });

  it('says when the place lookup fails', async () => {
    /** A failed lookup shows an error instead of an empty card. */
    server.use(http.get('*/api/place/profile', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })));
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not look up/i);
  });
});

const KABO: PlaceSearchResult = {
  label: 'Kåbovägen 1, Uppsala', lat: 59.88, lon: 17.68, kind: 'house', kommun: 'Uppsala kommun', in_pilot: true,
};
const GOTEBORG: PlaceSearchResult = {
  label: 'Kungsgatan 47, Göteborg', lat: 57.7, lon: 11.97, kind: 'house', kommun: 'Göteborgs kommun', in_pilot: false,
};

function searchReturns(results: PlaceSearchResult[] | null, onRequest?: (q: string) => void) {
  server.use(
    http.get('*/api/place/search', ({ request }) => {
      onRequest?.(new URL(request.url).searchParams.get('q') ?? '');
      if (results === null) {
        return HttpResponse.json({ detail: 'The address search is unavailable right now.' }, { status: 503 });
      }
      return HttpResponse.json(results);
    }),
  );
}

async function search(text: string) {
  const field = screen.getByRole('searchbox', { name: 'Search for a place' });
  await userEvent.type(field, `${text}{Enter}`);
}

describe('address search', () => {
  it('has a floating search field on the map panel', () => {
    /** The map panel has a search field for addresses and place names. */
    render(createElement(Harness), { wrapper: LanguageProvider });

    expect(screen.getByRole('searchbox', { name: 'Search for a place' })).toBeInTheDocument();
  });

  it('searches when Enter is pressed and lists the matches in order', async () => {
    /** Enter searches and lists the matches as the backend ranks them (pilot kommuner first). */
    searchReturns([KABO, GOTEBORG]);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('kåbovägen 1');

    const matches = within(await screen.findByRole('list', { name: 'Search results' })).getAllByRole('button');
    expect(matches.map((m) => m.textContent)).toEqual([expect.stringContaining('Kåbovägen 1, Uppsala'),
                                                        expect.stringContaining('Kungsgatan 47, Göteborg')]);
  });

  it('does not search while typing', async () => {
    /** Typing alone sends no request: results appear only after Enter. */
    const asked: string[] = [];
    searchReturns([KABO], (q) => asked.push(q));
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search for a place' }), 'kåbovägen');

    expect(asked).toEqual([]);
    expect(screen.queryByRole('list', { name: 'Search results' })).not.toBeInTheDocument();
  });

  it('proposes a pin at a chosen match and keeps the current card until it is confirmed', async () => {
    /** Choosing a match shows a proposed pin; the current pin and card stay. */
    searchReturns([KABO]);
    render(createElement(Harness, { start: { lat: 59.8505, lon: 17.641 } }), { wrapper: LanguageProvider });
    await screen.findByRole('heading', { name: 'Uppsala Kungsängen 7:8' });

    await search('kåbovägen 1');
    await userEvent.click(await screen.findByRole('button', { name: /Kåbovägen 1, Uppsala/ }));

    expect(screen.getByTestId('map')).toHaveAttribute('data-proposal', '59.88,17.68');
    expect(screen.getByTestId('map')).toHaveAttribute('data-pin', '59.8505,17.641');
    expect(screen.getByRole('heading', { name: 'Uppsala Kungsängen 7:8' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pin here' })).toBeInTheDocument();
  });

  it('pins the place when the proposal is confirmed', async () => {
    /** Confirming the proposal moves the pin there and shows its card. */
    searchReturns([KABO]);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('kåbovägen 1');
    await userEvent.click(await screen.findByRole('button', { name: /Kåbovägen 1, Uppsala/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Pin here' }));

    expect(screen.getByTestId('map')).toHaveAttribute('data-pin', '59.88,17.68');
    expect(screen.getByTestId('map')).toHaveAttribute('data-proposal', '');
    expect(await screen.findByRole('heading', { name: 'Uppsala Kåbo 1:1' })).toBeInTheDocument();
  });

  it('says so when nothing matched, and suggests a street address or pinning by hand', async () => {
    /** An empty result says no match and what to try instead. */
    searchReturns([]);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('xyzzy');

    expect(await screen.findByText(/no match/i)).toHaveTextContent(/street address/i);
    expect(screen.getByText(/no match/i)).toHaveTextContent(/pin/i);
  });

  it('says when the address search is unavailable', async () => {
    /** A failed search is shown as an alert, not as no match. */
    searchReturns(null);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('kungsgatan');

    expect(await screen.findByRole('alert')).toHaveTextContent(/address search is unavailable/i);
  });

  it('credits the address service under the results', async () => {
    /** The results list shows the search service's attribution. */
    searchReturns([KABO]);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('kåbovägen 1');

    await screen.findByRole('list', { name: 'Search results' });
    expect(screen.getByText(/Nominatim/)).toHaveTextContent(/OpenStreetMap/);
  });

  it("credits the kommun's address register when the matches come from it", async () => {
    /** A street address found in Uppsala's own register is credited to the kommun, not to OpenStreetMap. */
    searchReturns([{ ...KABO, kind: 'address' }]);
    render(createElement(Harness), { wrapper: LanguageProvider });

    await search('kåbovägen 1');

    await screen.findByRole('list', { name: 'Search results' });
    expect(screen.getByText(/address register/i)).toHaveTextContent(/Uppsala kommun/);
    expect(screen.queryByText(/Nominatim/)).not.toBeInTheDocument();
  });
});

function requestsTo(path: string): string[] {
  const seen: string[] = [];
  server.use(http.get(`*/api/place/review/${path}`, ({ request }) => {
    seen.push(new URL(request.url).search);
    return HttpResponse.json(path === 'coverage' ? reviewCoverage : reviewPlans);
  }));
  return seen;
}

const reviewToggle = () => screen.getByRole('button', { name: 'Review plan coverage' });

describe('review mode', () => {
  it('is off by default and the map is as before', () => {
    /** Before the user turns the review mode on, no coverage is fetched and the map gets no review layer. */
    const coverage = requestsTo('coverage');
    render(createElement(Harness), { wrapper: LanguageProvider });

    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('map')).toHaveAttribute('data-review', 'off');
    expect(coverage).toEqual([]);
  });

  it('colours the kommuner by coverage once turned on', async () => {
    /** Turning the review mode on fetches every kommun's coverage and hands it to the map. */
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(reviewToggle());

    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-kommuner', '3'));
  });

  it('sums up the coverage in the panel', async () => {
    /** The panel says how many kommuner have polygons, so the reviewer need not count colours. */
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(reviewToggle());

    expect(await screen.findByText(/2 of 3 kommuner with plan polygons/)).toBeInTheDocument();
  });

  it('fetches the plans in view once zoomed in to a kommun', async () => {
    /** Zoomed in past the threshold, the plans in the map's box are fetched for that box and drawn. */
    const plans = requestsTo('plans');
    render(createElement(Harness), { wrapper: LanguageProvider });
    await userEvent.click(reviewToggle());

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', '2'));
    expect(plans).toEqual([`?bbox=${encodeURIComponent(NACKA.join(','))}`]);
  });

  it('draws no plans zoomed out', async () => {
    /** Below the threshold the map shows the coverage colours only: no plans are fetched for the whole country. */
    const plans = requestsTo('plans');
    render(createElement(Harness), { wrapper: LanguageProvider });
    await userEvent.click(reviewToggle());
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', '2'));

    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }));

    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', ''));
    expect(plans).toHaveLength(1);
  });

  it('asks the reviewer to zoom in when the view had more plans than served', async () => {
    /** A truncated answer is said in the panel, so a missing polygon is not read as a missing plan. */
    server.use(http.get('*/api/place/review/plans', () => HttpResponse.json({ ...reviewPlans, truncated: true })));
    render(createElement(Harness), { wrapper: LanguageProvider });
    await userEvent.click(reviewToggle());

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    expect(await screen.findByText(/zoom in to see every plan/i)).toBeInTheDocument();
  });

  it('does not fetch plans while the review mode is off', async () => {
    /** Moving the map with the review mode off fetches nothing: the map behaves as it does today. */
    const plans = requestsTo('plans');
    render(createElement(Harness), { wrapper: LanguageProvider });
    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    expect(plans).toEqual([]);
  });

  it('clears the review layers when turned off', async () => {
    /** Turning the review mode off takes the coverage and the plans off the map. */
    render(createElement(Harness), { wrapper: LanguageProvider });
    await userEvent.click(reviewToggle());
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-kommuner', '3'));

    await userEvent.click(reviewToggle());

    expect(screen.getByTestId('map')).toHaveAttribute('data-review', 'off');
  });

  it('says when the coverage cannot be fetched', async () => {
    /** A failed coverage lookup is said in the panel instead of leaving the map uncoloured without a word. */
    server.use(http.get('*/api/place/review/coverage', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })));
    render(createElement(Harness), { wrapper: LanguageProvider });

    await userEvent.click(reviewToggle());

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not fetch the coverage/i);
  });
});

describe('page language', () => {
  it('shows the place card in Swedish once Svenska is chosen', async () => {
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
