// Acceptance tests for #37: ask about the pinned place in the chat. Temporary, folded into tests/unit/ by
// refactor-issue (PCR-0007). The base map is replaced by a stand-in: WebGL does not run in jsdom.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import PipelineTrace from '@/components/PipelineTrace';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import { placeFromHistory, placeLabel } from '@/lib/place';

import { kungsangen, street } from './mocks/place';
import { server } from './mocks/server';

Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement('button', { onClick: () => props.onMapClick({ lat: 59.8505, lon: 17.641 }) }, 'Click Kungsängen'),
}));

const PLACE_EVENT = {
  stage: 'place',
  data: { pin: { lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' }, profile: { property: null } },
};

function chat(sessionId: string | null = null) {
  return render(createElement(Chat, { sessionId, onSessionCreated: () => undefined, user: { name: 'anna' } }));
}

async function pinKungsangen() {
  await userEvent.click(screen.getByRole('button', { name: 'Open map' }));
  await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));
  await screen.findByRole('heading', { name: 'Uppsala Kungsängen 7:8' });
}

function sse(...events: object[]) {
  return new HttpResponse(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

describe('the pinned place in the chat', () => {
  it('shows the pinned place as a chip above the message input', async () => {
    /** Once a place is pinned, a chip names its property and kommun. */
    chat();
    await pinKungsangen();

    expect(screen.getByRole('button', { name: /Uppsala Kungsängen 7:8/ })).toBeInTheDocument();
  });

  it('opens the map from the chip', async () => {
    /** Clicking the chip opens the map panel. */
    chat();
    await pinKungsangen();
    await userEvent.click(screen.getByRole('button', { name: 'Close map' }));
    expect(screen.queryByRole('complementary', { name: 'Map' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Uppsala Kungsängen 7:8/ }));

    expect(screen.getByRole('complementary', { name: 'Map' })).toBeInTheDocument();
  });

  it('clears the pin from the chip', async () => {
    /** The chip's clear button removes the pin. */
    chat();
    await pinKungsangen();

    await userEvent.click(screen.getByRole('button', { name: 'Clear pin' }));

    expect(screen.queryByRole('button', { name: /Uppsala Kungsängen 7:8/ })).not.toBeInTheDocument();
  });

  it('sends the pinned place with the question', async () => {
    /** A question asked with a pin carries the pin and its label. */
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.post('*/api/chat/stream', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return sse({ type: 'session_id', session_id: 's9' }, { type: 'done', session_id: 's9' });
      }),
    );
    chat();
    await pinKungsangen();

    await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'What can I build here?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.place).toEqual({ lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' });
  });

  it('sends no place when nothing is pinned', async () => {
    /** Without a pin the question goes as today. */
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.post('*/api/chat/stream', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return sse({ type: 'session_id', session_id: 's9' }, { type: 'done', session_id: 's9' });
      }),
    );
    chat();

    await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'Hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.place ?? null).toBeNull();
  });

  it('restores the chip when the chat is reopened', async () => {
    /** Reopening a chat shows the place its latest answer was about. */
    server.use(
      http.get('*/api/sessions/s1', () =>
        HttpResponse.json([
          { id: 1, role: 'user', content: 'What can I build here?', session_id: 's1', created_at: '2026-10-25T10:00:00Z' },
          { id: 2, role: 'assistant', content: 'An answer.', session_id: 's1', created_at: '2026-10-25T10:00:05Z',
            status: 'done', trace: [PLACE_EVENT] },
        ]),
      ),
    );
    chat('s1');

    expect(await screen.findByRole('button', { name: /Uppsala Kungsängen 7:8/ })).toBeInTheDocument();
  });

  it('starts a new chat without the previous pin', async () => {
    /** The pin belongs to its chat session: a new chat has none. */
    server.use(
      http.get('*/api/sessions/s1', () =>
        HttpResponse.json([{ id: 2, role: 'assistant', content: 'An answer.', session_id: 's1',
                             created_at: '2026-10-25T10:00:05Z', status: 'done', trace: [PLACE_EVENT] }]),
      ),
    );
    const view = chat('s1');
    await screen.findByRole('button', { name: /Uppsala Kungsängen 7:8/ });

    view.rerender(createElement(Chat, { sessionId: null, onSessionCreated: () => undefined, user: { name: 'anna' } }));

    await waitFor(() => expect(screen.queryByRole('button', { name: /Uppsala Kungsängen 7:8/ })).not.toBeInTheDocument());
  });

  it('shows the place an answer used in the pipeline inspector', () => {
    /** The inspector has a Place step naming the pinned property. */
    render(createElement(PipelineTrace, {
      events: [{ stage: 'place', data: { pin: PLACE_EVENT.data.pin, profile: kungsangen } }],
    }));

    expect(screen.getByText('Place')).toBeInTheDocument();
    expect(screen.getByText(/Uppsala Kungsängen 7:8/)).toBeInTheDocument();
  });
});

describe('place labels', () => {
  it('labels a place by its property', () => {
    /** The chip label is the property's designation. */
    expect(placeLabel(kungsangen)).toBe('Uppsala Kungsängen 7:8');
  });

  it('labels a place without property by its point', () => {
    /** Without a property the label is the point. */
    expect(placeLabel(street)).toBe('59.85050, 17.64100');
  });

  it('takes the latest place of a history', () => {
    /** The latest answer with a place wins; answers without one are skipped. */
    const older = { stage: 'place', data: { pin: { lat: 1, lon: 2, label: 'Old' }, profile: {} } };
    expect(placeFromHistory([[older], null, [PLACE_EVENT], [{ stage: 'call', data: {} }]])).toEqual(
      { lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' });
    expect(placeFromHistory([null, []])).toBeNull();
  });
});
