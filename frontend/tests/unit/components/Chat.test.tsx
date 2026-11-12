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

describe('questions with options', () => {
  const ASKED = [
    { id: 1, role: 'user', content: 'Can I build 20 apartments in Södermalm?', session_id: 's2',
      created_at: '2026-10-25T10:00:00Z' },
    { id: 2, role: 'assistant', content: 'Which place do you mean?', session_id: 's2',
      created_at: '2026-10-25T10:00:05Z', status: 'done',
      trace: [{ type: 'pipeline', stage: 'choices',
                data: { options: ['The pinned Uppsala property', 'A site in Södermalm'] } }] },
  ];

  it('shows the options of the last answer as buttons', async () => {
    /** When the agent asks the user to choose, each option is a button under its question. */
    server.use(http.get('*/api/sessions/s2', () => HttpResponse.json(ASKED)));
    chat('s2');

    expect(await screen.findByRole('button', { name: 'The pinned Uppsala property' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'A site in Södermalm' })).toBeInTheDocument();
  });

  it('sends the clicked option as the next message', async () => {
    /** Clicking an option answers with that option, as if the user had typed it. */
    let sent: { messages: { role: string; content: string }[] } | null = null;
    server.use(
      http.get('*/api/sessions/s2', () => HttpResponse.json(ASKED)),
      http.post('*/api/chat/stream', async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return sse({ type: 'session_id', session_id: 's2' }, { type: 'done', session_id: 's2' });
      }),
    );
    chat('s2');

    await userEvent.click(await screen.findByRole('button', { name: 'A site in Södermalm' }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.messages.at(-1)).toEqual({ role: 'user', content: 'A site in Södermalm' });
    expect((sent as unknown as { answer_to_question?: boolean }).answer_to_question).toBe(true);
  });

  it('offers to pin the place on the map, which opens the map', async () => {
    /** A question that needs a place can come with a button that opens the map. */
    server.use(http.get('*/api/sessions/s3', () => HttpResponse.json([
      ASKED[0],
      { ...ASKED[1], session_id: 's3',
        trace: [{ type: 'pipeline', stage: 'choices', data: { options: ['Answer generally'], offer_pin: true } }] },
    ])));
    chat('s3');

    await userEvent.click(await screen.findByRole('button', { name: 'Pin it on the map' }));

    expect(await screen.findByTestId('map')).toBeInTheDocument();
  });

  it('answers with the place once the user has pinned it from the button', async () => {
    /** "Pin it on the map" opens the map; the pin then goes back to the agent, with the place, on its own. */
    let sent: { messages: { role: string; content: string }[]; place?: unknown } | null = null;
    server.use(
      http.get('*/api/sessions/s3', () => HttpResponse.json([
        ASKED[0],
        { ...ASKED[1], session_id: 's3',
          trace: [{ type: 'pipeline', stage: 'choices', data: { options: ['Answer generally'], offer_pin: true } }] },
      ])),
      http.post('*/api/chat/stream', async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return sse({ type: 'session_id', session_id: 's3' }, { type: 'done', session_id: 's3' });
      }),
    );
    chat('s3');

    await userEvent.click(await screen.findByRole('button', { name: 'Pin it on the map' }));
    expect(screen.getByText(/click the map to pin the place/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Click Kungsängen' }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.messages.at(-1)!.content).toMatch(/Uppsala Kungsängen 7:8/);
    expect(sent!.place).toEqual({ lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' });
    expect((sent as unknown as { answer_to_question?: boolean }).answer_to_question).toBe(true);
  });

  it('says the user can also type their own answer', async () => {
    server.use(http.get('*/api/sessions/s2', () => HttpResponse.json(ASKED)));
    chat('s2');

    expect(await screen.findByText(/or type your own answer/i)).toBeInTheDocument();
  });

  it('shows no options under an earlier answer', async () => {
    /** Once the user has answered, the old question's buttons are gone. */
    server.use(http.get('*/api/sessions/s2', () => HttpResponse.json([
      ...ASKED,
      { id: 3, role: 'user', content: 'A site in Södermalm', session_id: 's2', created_at: '2026-10-25T10:01:00Z' },
      { id: 4, role: 'assistant', content: 'In Södermalm ...', session_id: 's2', created_at: '2026-10-25T10:01:30Z',
        status: 'done', trace: [] },
    ])));
    chat('s2');

    await screen.findByText(/In Södermalm/);
    expect(screen.queryByRole('button', { name: 'The pinned Uppsala property' })).not.toBeInTheDocument();
  });
});

// --- the claim check of an answer -------------------------------------------------------------------

const A = 'a'.repeat(16);
const B = 'b'.repeat(16);
const HOUSE = 'Bygglov is needed for a new house';
const FEE = 'The fee is 12 000 kr';
const SOURCES = '\n\n---\n**Sources**\n- [1] PBL, 9 kap. 4 §\n- [2] Ydre – Bygglovstaxa';
const ANSWER = `${HOUSE} [1]. ${FEE} [2].${SOURCES}`;
const NOT_SUPPORTED = 'Not supported by the cited sources';
const NO_SOURCE = 'No source cited';
const NOTICE = 'The claims in this answer could not be checked.';

const CITATIONS = {
  stage: 'citations',
  data: {
    items: [
      { n: 1, label: 'PBL, 9 kap. 4 §', chunks: [{ source: 'PBL, 9 kap. 4 §', chunk_id: A, content: 'Bygglov krävs.' }] },
      { n: 2, label: 'Ydre – Bygglovstaxa', chunks: [{ source: 'Ydre – Bygglovstaxa', chunk_id: B, content: 'Taxa.' }] },
    ],
  },
};

const HOUSE_SUPPORTED = {
  text: HOUSE, verdict: 'supported', chunk_ids: [A],
  supporting: [{ chunk_id: A, sentence: 'Bygglov krävs.' }],
};

function checked(...claims: object[]) {
  return { stage: 'claim_check', data: { status: 'checked', claims } };
}

function answer(id: number, trace: object[], extra: object = {}) {
  return { id, role: 'assistant', content: ANSWER, session_id: 's1', created_at: '2026-11-12T10:00:05Z',
           status: 'done', trace, ...extra };
}

function history(...messages: object[]) {
  server.use(http.get('*/api/sessions/s1', () => HttpResponse.json([
    { id: 1, role: 'user', content: 'Do I need bygglov in Ydre?', session_id: 's1', created_at: '2026-11-12T10:00:00Z' },
    ...messages,
  ])));
}



// A stream that sends its events and then stays open, as while the claims are being checked
function openStream(...events: object[]) {
  const body = new ReadableStream({
    start(controller) {
      for (const event of events) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
    },
  });
  return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } });
}

async function ask() {
  await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'Do I need bygglov in Ydre?');
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));
}

describe('claims the sources do not back', () => {
  it('marks an unsupported claim in the answer', async () => {
    /** A claim still unsupported after the check is marked in the answer as not supported by its sources. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
      { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [] })]));
    chat('s1');

    expect(await screen.findByTitle(NOT_SUPPORTED)).toHaveTextContent(FEE);
  });

  it('marks an uncited claim in the answer', async () => {
    /** A claim with no source is marked in the answer as having none. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
      { text: FEE, verdict: 'uncited', chunk_ids: [], supporting: [] })]));
    chat('s1');

    expect(await screen.findByTitle(NO_SOURCE)).toHaveTextContent(FEE);
  });

  it('marks only the claims the sources do not back', async () => {
    /** A supported claim is left unmarked beside a flagged one. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
      { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [] })]));
    chat('s1');

    await screen.findByTitle(NOT_SUPPORTED);
    const flagged = [...screen.queryAllByTitle(NOT_SUPPORTED), ...screen.queryAllByTitle(NO_SOURCE)];
    expect(flagged.map((element) => element.textContent)).toEqual([FEE]);
  });

  it('lists a flagged claim below the answer when its text is not in the answer', async () => {
    /** A flag whose text cannot be found in the answer is still shown, under the answer. */
    history(answer(2, [CITATIONS, checked(
      { text: 'Bygglov takes ten weeks', verdict: 'unsupported', chunk_ids: [B], supporting: [] })]));
    chat('s1');

    expect(await screen.findByText(/Unchecked claim: Bygglov takes ten weeks/)).toBeInTheDocument();
  });
});

describe('an answer whose check could not run', () => {
  it('says that its claims could not be checked', async () => {
    /** A failed check leaves the answer with a one-line notice. */
    history(answer(2, [CITATIONS, { stage: 'claim_check', data: { status: 'failed', claims: [] } }]));
    chat('s1');

    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
  });

  it('keeps the answer itself', async () => {
    /** The answer of a failed check is shown in full beside the notice. */
    history(answer(2, [CITATIONS, { stage: 'claim_check', data: { status: 'failed', claims: [] } }]));
    chat('s1');

    await screen.findByText(NOTICE);
    expect(screen.getByText(new RegExp(FEE))).toBeInTheDocument();
  });

  it('gives no notice to an answer saved before the check existed', async () => {
    /** Of an old answer without a check and a failed one, only the failed one has the notice. */
    history(answer(2, [CITATIONS]), answer(4, [CITATIONS, { stage: 'claim_check', data: { status: 'failed', claims: [] } }]));
    chat('s1');

    await screen.findByText(NOTICE);
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });
});

describe('while the claims are being checked', () => {
  it('shows it under the streamed answer', async () => {
    /** Once the answer has streamed and the check starts, the answer says its claims are being checked. */
    server.use(http.post('*/api/chat/stream', () => openStream(
      { type: 'session_id', session_id: 's9' },
      { type: 'response.output_text.delta', delta: ANSWER },
      { type: 'thinking', label: 'Checking the claims' },
    )));
    chat();
    await ask();

    expect(await screen.findByText('Checking claims…')).toBeInTheDocument();
  });

  it('shows it on an answer reopened before its check is done', async () => {
    /** An answer saved with its text but no check yet, still generating, shows that its claims are being checked. */
    history(answer(2, [CITATIONS], { status: 'streaming' }));
    chat('s1');

    expect(await screen.findByText('Checking claims…')).toBeInTheDocument();
  });

  it('replaces the shown answer with the rewritten one', async () => {
    /** A rewritten answer sent after the check replaces the text already shown. */
    server.use(http.post('*/api/chat/stream', () => sse(
      { type: 'session_id', session_id: 's9' },
      { type: 'response.output_text.delta', delta: ANSWER },
      { type: 'answer_replaced', content: `${HOUSE} [1].\n\n---\n**Sources**\n- [1] PBL, 9 kap. 4 §` },
      { type: 'response.completed' },
      { type: 'done', session_id: 's9' },
    )));
    server.use(http.get('*/api/sessions/s9', () => HttpResponse.json([])));
    chat();
    await ask();

    await waitFor(() => expect(screen.queryByText(new RegExp(FEE))).not.toBeInTheDocument());
  });
});
