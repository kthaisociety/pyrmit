// Acceptance tests for #35: pin a place in Uppsala and see its property and plans. Temporary, folded into
// tests/unit/ by refactor-issue (PCR-0007). The base map is replaced by a stand-in: WebGL does not run in jsdom.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import PlaceCard from '@/components/place/PlaceCard';
import PlacePanel from '@/components/place/PlacePanel';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import type { Pin } from '@/lib/place';

import { server } from './mocks/server';
import { kaboOutside, kungsangen, notCovered, propertyUnavailable, street } from './mocks/place';

// jsdom has no layout: the chat scrolls to its last message on render
Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement(
      'div',
      { 'data-testid': 'map', 'data-outlines': String(props.outlines.length),
        'data-pin': props.pin ? `${props.pin.lat},${props.pin.lon}` : '' },
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.8505, lon: 17.641 }) }, 'Click Kungsängen'),
      createElement('button', { onClick: () => props.onMapClick({ lat: 59.88, lon: 17.68 }) }, 'Click Kåbo'),
    ),
}));

function Harness() {
  const [pin, setPin] = useState<Pin | null>(null);
  return createElement(PlacePanel, { pin, onPinChange: setPin, onClose: () => undefined });
}

function card(profile = kungsangen) {
  render(createElement(PlaceCard, { profile }));
}

describe('map panel', () => {
  it('opens beside the conversation from the chat', async () => {
    /** The chat has a button that opens the map panel next to the messages. */
    render(createElement(Chat, { sessionId: null, onSessionCreated: () => undefined, user: { name: 'anna' } }));

    await userEvent.click(screen.getByRole('button', { name: 'Open map' }));

    expect(screen.getByRole('complementary', { name: 'Map' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Ask about building permits...')).toBeInTheDocument();
  });

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

describe('place card', () => {
  it('shows the property', () => {
    /** The card names the property at the pin and its kommun. */
    card();
    expect(screen.getByRole('heading', { name: 'Uppsala Kungsängen 7:8' })).toBeInTheDocument();
    expect(screen.getByText('Kommun: Uppsala')).toBeInTheDocument();
  });

  it('lists the plans in force newest first, each with a link to its documents', () => {
    /** Plans come newest laga kraft date first with aktbeteckning, name, date and a document link. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    const refs = plans.map((item) => item.textContent?.match(/0380-[PO]\d{4}\/\d+/)?.[0]);
    expect(refs).toEqual(['0380-P2012/9', '0380-O2005/1', '0380-P2002/5', '0380-P1990/3']);
    expect(within(plans[2]).getByText('Del av Atle, Kungsängen 7:8')).toBeInTheDocument();
    expect(within(plans[2]).getByText(/2002-01-09/)).toBeInTheDocument();
    expect(within(plans[2]).getByRole('link', { name: /documents/i })).toHaveAttribute(
      'href', 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5');
  });

  it('marks tillägg and områdesbestämmelser among the plans', () => {
    /** A tillägg and områdesbestämmelser are labelled as such in the plan list. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(plans[0]).toHaveTextContent('Tillägg');
    expect(plans[1]).toHaveTextContent('Områdesbestämmelser');
  });

  it('lists the land-use zones with code and wording, as interpreted boundaries', () => {
    /** Each zone shows its code, wording, share of the property and the interpreted-boundary caveat. */
    card();
    const zones = within(screen.getByRole('list', { name: 'Användning' })).getAllByRole('listitem');
    expect(zones[0]).toHaveTextContent('BCK');
    expect(zones[0]).toHaveTextContent('Bostäder, Centrumfunktion, Kontor');
    expect(zones[0]).toHaveTextContent('75 %');
    expect(screen.getAllByText(/interpreted boundaries/i).length).toBeGreaterThan(0);
  });

  it('points to indexed provisions and says when they are not indexed', () => {
    /** A plan with provisions in the corpus says so; the others say the provisions are not indexed. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(plans[2]).toHaveTextContent(/provisions in the corpus/i);
    expect(plans[3]).toHaveTextContent(/provisions not indexed/i);
  });

  it('shows plans in progress apart, as not binding', () => {
    /** Plans in progress have their own section with their stage and a not-binding label. */
    card();
    const pending = screen.getByRole('list', { name: 'Plans in progress' });
    expect(pending).toHaveTextContent('Kungsängen 7:8 m.fl.');
    expect(pending).toHaveTextContent('Samråd');
    expect(pending).toHaveTextContent(/not binding/i);
  });

  it('says the property is inside a detaljplan', () => {
    /** A property under a plan in force is marked inside a detaljplan. */
    card();
    expect(screen.getByText(/inside a detaljplan/i)).toBeInTheDocument();
  });

  it('says the property is outside a detaljplan', () => {
    /** A property with no plan, in a complete plan source, is marked outside a detaljplan. */
    card(kaboOutside);
    expect(screen.getByText(/outside a detaljplan/i)).toBeInTheDocument();
  });

  it('asks to move the pin when there is no property', () => {
    /** A pin on a street, park or water says so and asks to move the pin. */
    card(street);
    expect(screen.getByText(/no property here/i)).toBeInTheDocument();
    expect(screen.getByText(/move the pin/i)).toBeInTheDocument();
  });

  it('says the place is not covered yet outside the pilot kommuner', () => {
    /** Outside the pilot kommuner the card says the place is not covered yet. */
    card(notCovered);
    expect(screen.getByText(/not covered yet/i)).toBeInTheDocument();
  });

  it('says when the property service is unavailable', () => {
    /** A failed property lookup is shown as unavailable, not as no property. */
    card(propertyUnavailable);
    expect(screen.getByText(/property lookup is unavailable/i)).toBeInTheDocument();
  });

  it('names the source and date of every row', () => {
    /** Every plan, zone and plan in progress shows its source and snapshot date. */
    card();
    const rows = [
      ...within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem'),
      ...within(screen.getByRole('list', { name: 'Användning' })).getAllByRole('listitem'),
      ...within(screen.getByRole('list', { name: 'Plans in progress' })).getAllByRole('listitem'),
    ];
    for (const item of rows) expect(item).toHaveTextContent('Uppsala kommun · 2026-10-25');
  });

  it('says it is registry data, not a decision', () => {
    /** The card carries the registry-data note. */
    card();
    expect(screen.getByText(/Registry data, not a decision/)).toBeInTheDocument();
  });
});
