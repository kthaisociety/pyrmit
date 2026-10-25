// Unit tests for components/place/PlacePanel.tsx. The base map is replaced by a stand-in: WebGL does not run in jsdom.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import PlacePanel from '@/components/place/PlacePanel';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import type { Pin, PlaceSearchResult } from '@/lib/place';

import { kungsangen } from '../../../mocks/place';
import { server } from '../../../mocks/server';

vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement(
      'div',
      { 'data-testid': 'map', 'data-outlines': String(props.outlines.length),
        'data-pin': props.pin ? `${props.pin.lat},${props.pin.lon}` : '',
        'data-proposal': props.proposal ? `${props.proposal.lat},${props.proposal.lon}` : '' },
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.8505, lon: 17.641 }) }, 'Click Kungsängen'),
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.88, lon: 17.68 }) }, 'Click Kåbo'),
    ),
}));

function Harness({ start = null }: { start?: Pin | null }) {
  const [pin, setPin] = useState<Pin | null>(start);
  return createElement(PlacePanel, { pin, onPinChange: setPin, onClose: () => undefined });
}

describe('map panel', () => {
  it('places a pin where the map is clicked and shows the place card', async () => {
    /** A click on the map puts the pin there and the card of that place appears. */
    render(createElement(Harness));

    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));

    expect(screen.getByTestId('map')).toHaveAttribute('data-pin', '59.8505,17.641');
    expect(await screen.findByText('Uppsala Kungsängen 7:8')).toBeInTheDocument();
  });

  it('moves the pin on a second click and shows the new place', async () => {
    /** Clicking elsewhere moves the pin and replaces the card. */
    render(createElement(Harness));
    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
    await screen.findByText('Uppsala Kungsängen 7:8');

    await userEvent.click(screen.getByRole('button', { name: 'Click Kåbo' }));

    expect(await screen.findByText('Uppsala Kåbo 1:1')).toBeInTheDocument();
    expect(screen.queryByText('Uppsala Kungsängen 7:8')).not.toBeInTheDocument();
  });

  it('outlines the property, its plans and its zones on the map', async () => {
    /** The map gets one outline for the property, each plan and each zone. */
    render(createElement(Harness));

    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
    await screen.findByText('Uppsala Kungsängen 7:8');

    const expected = 1 + kungsangen.plans.length + kungsangen.zones.length;
    expect(screen.getByTestId('map')).toHaveAttribute('data-outlines', String(expected));
  });

  it('says when the place lookup fails', async () => {
    /** A failed lookup shows an error instead of an empty card. */
    server.use(http.get('*/api/place/profile', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })));
    render(createElement(Harness));

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
    render(createElement(Harness));

    expect(screen.getByRole('searchbox', { name: 'Search for a place' })).toBeInTheDocument();
  });

  it('searches when Enter is pressed and lists the matches in order', async () => {
    /** Enter searches and lists the matches as the backend ranks them (pilot kommuner first). */
    searchReturns([KABO, GOTEBORG]);
    render(createElement(Harness));

    await search('kåbovägen 1');

    const matches = within(await screen.findByRole('list', { name: 'Search results' })).getAllByRole('button');
    expect(matches.map((m) => m.textContent)).toEqual([expect.stringContaining('Kåbovägen 1, Uppsala'),
                                                        expect.stringContaining('Kungsgatan 47, Göteborg')]);
  });

  it('does not search while typing', async () => {
    /** Typing alone sends no request: results appear only after Enter. */
    const asked: string[] = [];
    searchReturns([KABO], (q) => asked.push(q));
    render(createElement(Harness));

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search for a place' }), 'kåbovägen');

    expect(asked).toEqual([]);
    expect(screen.queryByRole('list', { name: 'Search results' })).not.toBeInTheDocument();
  });

  it('proposes a pin at a chosen match and keeps the current card until it is confirmed', async () => {
    /** Choosing a match shows a proposed pin; the current pin and card stay. */
    searchReturns([KABO]);
    render(createElement(Harness, { start: { lat: 59.8505, lon: 17.641 } }));
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
    render(createElement(Harness));

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
    render(createElement(Harness));

    await search('xyzzy');

    expect(await screen.findByText(/no match/i)).toHaveTextContent(/street address/i);
    expect(screen.getByText(/no match/i)).toHaveTextContent(/pin/i);
  });

  it('says when the address search is unavailable', async () => {
    /** A failed search is shown as an alert, not as no match. */
    searchReturns(null);
    render(createElement(Harness));

    await search('kungsgatan');

    expect(await screen.findByRole('alert')).toHaveTextContent(/address search is unavailable/i);
  });

  it('credits the address service under the results', async () => {
    /** The results list shows the search service's attribution. */
    searchReturns([KABO]);
    render(createElement(Harness));

    await search('kåbovägen 1');

    await screen.findByRole('list', { name: 'Search results' });
    expect(screen.getByText(/Nominatim/)).toHaveTextContent(/OpenStreetMap/);
  });
});
