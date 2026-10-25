// Unit tests for components/place/PlacePanel.tsx. The base map is replaced by a stand-in: WebGL does not run in jsdom.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import PlacePanel from '@/components/place/PlacePanel';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import type { Pin } from '@/lib/place';

import { kungsangen } from '../../../mocks/place';
import { server } from '../../../mocks/server';

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

