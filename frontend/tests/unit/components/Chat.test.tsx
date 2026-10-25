// Unit tests for components/Chat.tsx.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import type { PlaceMapProps } from '@/components/place/PlaceMap';

import { server } from '../../mocks/server';

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

describe('map panel', () => {
  it('opens beside the conversation from the chat', async () => {
    /** The chat has a button that opens the map panel next to the messages. */
    render(createElement(Chat, { sessionId: null, onSessionCreated: () => undefined, user: { name: 'anna' } }));

    await userEvent.click(screen.getByRole('button', { name: 'Open map' }));

    expect(screen.getByRole('complementary', { name: 'Map' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Ask about building permits...')).toBeInTheDocument();
  });

});

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

});
