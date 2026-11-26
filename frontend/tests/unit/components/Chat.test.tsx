// Unit tests for components/Chat.tsx.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import type { PlaceMapProps } from '@/components/place/PlaceMap';
import { LANGUAGE_STORAGE_KEY, LanguageProvider } from '@/lib/i18n';

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
    render(createElement(Chat, { sessionId: null, onSessionCreated: () => undefined, user: { name: 'anna' } }), { wrapper: LanguageProvider });

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
  return render(createElement(Chat, { sessionId, onSessionCreated: () => undefined, user: { name: 'anna' } }), { wrapper: LanguageProvider });
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

  it('says why the server refused the question', async () => {
    /** No API key (or any refusal before the answer): the reply shows the server's reason instead of vanishing. */
    server.use(
      http.post('*/api/chat/stream', () =>
        HttpResponse.json({ detail: 'No OpenRouter API key: add yours in Settings to chat.' }, { status: 400 }),
      ),
    );
    chat();

    await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'Hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText(/No OpenRouter API key: add yours in Settings to chat\./)).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
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
const MAY_NOT_BACK = 'The sources may not back this claim';
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
  const FEE_FLAGGED = { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [FEE] };
  const FEE_UNCITED = { text: FEE, verdict: 'uncited', chunk_ids: [], supporting: [], unbacked: [] };
  const flags = () => [...screen.queryAllByRole('button', { name: MAY_NOT_BACK }),
                       ...screen.queryAllByRole('button', { name: NO_SOURCE })];
  // The text a flag is about: tinted while the flag is hovered
  const tinted = () => [...document.querySelectorAll('[data-tinted="true"]')].map((element) => element.textContent);

  it('puts a red flag after a claim its sources do not back', async () => {
    /** A claim the check found unsupported gets a flag saying the sources may not back it. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    expect(await screen.findByRole('button', { name: MAY_NOT_BACK })).toBeInTheDocument();
  });

  it('puts a flag with its own text after a claim with no source', async () => {
    /** A claim with no source cited gets a flag saying so. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_UNCITED)]));
    chat('s1');

    expect(await screen.findByRole('button', { name: NO_SOURCE })).toBeInTheDocument();
  });

  it('flags only the claims the sources do not back', async () => {
    /** A supported claim gets no flag beside a flagged one. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await screen.findByRole('button', { name: MAY_NOT_BACK });
    expect(flags()).toHaveLength(1);
  });

  it('leaves the flagged text without an underline', async () => {
    /** The answer text is unmarked: only the flag shows. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await screen.findByRole('button', { name: MAY_NOT_BACK });
    expect(screen.getByText(FEE).className).not.toContain('underline');
    expect(tinted()).toEqual([]);
  });

  it('tints the text a flag is about while the flag is hovered', async () => {
    /** Hovering a flag shows which text it concerns. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await userEvent.hover(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    expect(tinted()).toEqual([FEE]);
  });

  it('puts the flag after the sentence that lacks backing, not after the whole claim', async () => {
    /** When only part of a claim lacks backing, the flag is about that sentence alone. */
    const LATE = 'It is paid in advance';
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
      { text: `${FEE}. ${LATE}`, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [LATE] })],
      { content: `${HOUSE} [1]. ${FEE}. ${LATE} [2].${SOURCES}` }));
    chat('s1');

    await userEvent.hover(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    expect(tinted()).toEqual([LATE]);
  });

  it('puts the flag after the whole claim when the result names no sentence', async () => {
    /** A check result saved before it named the sentences lacking backing flags the whole claim. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
      { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [] })]));
    chat('s1');

    await userEvent.hover(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    expect(tinted()).toEqual([FEE]);
  });

  it('lists a flagged claim below the answer when its text is not in the answer', async () => {
    /** A flag whose text cannot be found in the answer is still shown, under the answer, with its flag. */
    history(answer(2, [CITATIONS, checked(
      { text: 'Bygglov takes ten weeks', verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [] })]));
    chat('s1');

    expect(await screen.findByText('Bygglov takes ten weeks')).toBeInTheDocument();
    expect(flags()).toHaveLength(1);
  });

  it('gives the hover text in Swedish on the Swedish page', async () => {
    /** The flag's text follows the page language. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    expect(await screen.findByRole('button', { name: 'Källorna stöder kanske inte det här påståendet' }))
      .toBeInTheDocument();
    expect(screen.getByText('1 påstående kunde inte bekräftas av källorna.')).toBeInTheDocument();
  });
});

describe('the count of claims that could not be confirmed', () => {
  const flagged = (text: string) => ({ text, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [] });

  it('says that one claim could not be confirmed', async () => {
    /** One line under the answer counts the flagged claims. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, flagged(FEE))]));
    chat('s1');

    expect(await screen.findByText('1 claim could not be confirmed by the sources.')).toBeInTheDocument();
  });

  it('counts every flagged claim', async () => {
    /** Two flagged claims give a count of two. */
    history(answer(2, [CITATIONS, checked(flagged(HOUSE), flagged(FEE))]));
    chat('s1');

    expect(await screen.findByText('2 claims could not be confirmed by the sources.')).toBeInTheDocument();
  });

  it('shows no count and no flag when nothing is flagged', async () => {
    /** An answer whose claims are all supported carries neither. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED)]));
    chat('s1');

    await screen.findByText(new RegExp(HOUSE));
    expect(screen.queryByText(/could not be confirmed/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: MAY_NOT_BACK })).not.toBeInTheDocument();
  });

  it('shows no count and no flag on an answer saved before the check', async () => {
    /** An answer without a check result is shown as it was. */
    history(answer(2, [CITATIONS]));
    chat('s1');

    await screen.findByText(new RegExp(HOUSE));
    expect(screen.queryByText(/could not be confirmed/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: MAY_NOT_BACK })).not.toBeInTheDocument();
  });
});

describe('a flag opens the claim with its sources', () => {
  const CLAIM_VIEW = { name: 'Claim that could not be confirmed' };
  const FEE_FLAGGED = { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [FEE] };
  const FEE_UNCITED = { text: FEE, verdict: 'uncited', chunk_ids: [], supporting: [], unbacked: [] };

  it('shows the claim and why it is flagged', async () => {
    /** Clicking a flag opens the source panel with the claim and its reason on top. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    const view = within(screen.getByRole('region', CLAIM_VIEW));
    expect(view.getByText(FEE)).toBeInTheDocument();
    expect(view.getByText('The cited sources do not say this.')).toBeInTheDocument();
  });

  it('shows the source texts the claim cites', async () => {
    /** The cited chunks follow the claim, so the reader can compare. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    const panel = within(screen.getByRole('complementary'));
    expect(panel.getAllByText('Taxa.').length).toBeGreaterThan(0);
    expect(panel.queryByText('Bygglov krävs.')).not.toBeInTheDocument();
  });

  it('shows a claim with no source without a source part', async () => {
    /** An uncited claim opens the panel with the claim and the reason only. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_UNCITED)]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: NO_SOURCE }));
    const panel = within(screen.getByRole('complementary'));
    expect(panel.getByText('No source is cited for this claim.')).toBeInTheDocument();
    expect(panel.queryByText('Taxa.')).not.toBeInTheDocument();
    expect(panel.queryByText('Bygglov krävs.')).not.toBeInTheDocument();
  });

  it('shows the other claim when another flag is clicked', async () => {
    /** The panel follows the flag clicked last. */
    history(answer(2, [CITATIONS, checked(
      { text: HOUSE, verdict: 'unsupported', chunk_ids: [A], supporting: [], unbacked: [HOUSE] }, FEE_UNCITED)]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    await userEvent.click(screen.getByRole('button', { name: NO_SOURCE }));
    const view = within(screen.getByRole('region', CLAIM_VIEW));
    expect(view.getByText(FEE)).toBeInTheDocument();
    expect(view.queryByText(HOUSE)).not.toBeInTheDocument();
  });

  it('opens a claim listed under the answer', async () => {
    /** A flagged claim whose text is not in the answer opens the same panel from its line under the answer. */
    history(answer(2, [CITATIONS, checked(
      { text: 'Bygglov takes ten weeks', verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [] })]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    expect(within(screen.getByRole('region', CLAIM_VIEW)).getByText('Bygglov takes ten weeks')).toBeInTheDocument();
  });

  it('opens a citation number without a claim view', async () => {
    /** A citation chip still opens its source alone. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_FLAGGED)]));
    chat('s1');

    await screen.findByRole('button', { name: MAY_NOT_BACK });
    await userEvent.click(screen.getByRole('button', { name: '1' }));
    expect(screen.getByRole('complementary')).toBeInTheDocument();
    expect(screen.queryByRole('region', CLAIM_VIEW)).not.toBeInTheDocument();
  });

  it('gives the reason in Swedish on the Swedish page', async () => {
    /** The claim view follows the page language. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED, FEE_UNCITED)]));
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: 'Ingen källa angiven' }));
    expect(screen.getByText('Ingen källa anges för det här påståendet.')).toBeInTheDocument();
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

describe('the source panel of a checked answer', () => {
  const UNDERLINED = 'Supports a claim in the answer';
  const NEEDED = 'Bygglov krävs för en ny byggnad.';
  const FEE_RULE = 'Avgiften är 12 000 kr.';
  const PANEL_CITATIONS = {
    stage: 'citations',
    data: {
      items: [
        { n: 1, label: 'PBL, 9 kap. 4 §', chunks: [{ source: 'PBL, 9 kap. 4 §', chunk_id: A,
          content: `${NEEDED} Ansökan lämnas till byggnadsnämnden. ${FEE_RULE}` }] },
        { n: 2, label: 'Ydre – Bygglovstaxa', chunks: [{ source: 'Ydre – Bygglovstaxa', chunk_id: B, content: 'Taxa.' }] },
      ],
    },
  };

  function supportedBy(text: string, sentence: string) {
    return { text, verdict: 'supported', chunk_ids: [A], supporting: [{ chunk_id: A, sentence }] };
  }

  async function openFirstChip() {
    chat('s1');
    await userEvent.click((await screen.findAllByRole('button', { name: '1' }))[0]);
  }

  function underlined(): (string | null)[] {
    return screen.queryAllByTitle(UNDERLINED).map((element) => element.textContent);
  }

  it('underlines the sentence of the cited chunk that backs a claim', async () => {
    /** After the check, the chip's panel underlines the chunk sentence that supports the claim. */
    history(answer(2, [PANEL_CITATIONS, checked(supportedBy(HOUSE, NEEDED))]));
    await openFirstChip();

    expect(underlined()).toEqual([NEEDED]);
  });

  it('underlines the sentences of every claim that cites the chunk', async () => {
    /** A chunk cited by two claims underlines the supporting sentence of each. */
    history(answer(2, [PANEL_CITATIONS, checked(supportedBy(HOUSE, NEEDED), supportedBy(FEE, FEE_RULE))]));
    await openFirstChip();

    expect(underlined()).toEqual([NEEDED, FEE_RULE]);
  });

  it('shows the chunk without underline for an answer saved before the check', async () => {
    /** An old message with no check result opens its chunk with nothing underlined. */
    history(answer(2, [PANEL_CITATIONS]));
    await openFirstChip();

    expect(underlined()).toEqual([]);
  });

  it('shows the chunk without underline when the check failed', async () => {
    /** A failed check has no supporting sentences, so nothing in the chunk is underlined. */
    history(answer(2, [PANEL_CITATIONS, { stage: 'claim_check', data: { status: 'failed', claims: [] } }]));
    await openFirstChip();

    expect(underlined()).toEqual([]);
  });
});

// A stream whose deltas the test sends one at a time; `null` ends it
function liveStream() {
  let push: (event: object | null) => void = () => {};
  server.use(http.post('*/api/chat/stream', () => {
    const body = new ReadableStream({
      start(controller) {
        push = (event) => (event === null ? controller.close()
          : controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)));
      },
    });
    return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } });
  }));
  return (event: object | null) => push(event);
}

describe('typing while an answer is on its way', () => {
  const INPUT = 'Ask about building permits...';

  async function streaming() {
    const push = liveStream();
    const view = chat();
    await ask();
    push({ type: 'session_id', session_id: 's9' });
    push({ type: 'response.output_text.delta', delta: 'The first part.' });
    await screen.findByText(/The first part/);
    return Object.assign(push, { view });
  }

  it('takes the next question while the answer streams', async () => {
    /** The input stays open while an answer streams, so the next question can be written. */
    await streaming();

    await userEvent.type(screen.getByPlaceholderText(INPUT), 'And in Uppsala?');

    expect(screen.getByPlaceholderText(INPUT)).toHaveValue('And in Uppsala?');
  });

  it('does not send the next question before the answer is done', async () => {
    /** Send stays off and Enter does nothing until the answer is finished; the typed question is kept. */
    let posts = 0;
    await streaming();
    server.use(http.post('*/api/chat/stream', () => {
      posts += 1;
      return sse({ type: 'done', session_id: 's9' });
    }));

    await userEvent.type(screen.getByPlaceholderText(INPUT), 'And in Uppsala?{Enter}');

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(posts).toBe(0);
    expect(screen.getByPlaceholderText(INPUT)).toHaveValue('And in Uppsala?');
  });

  it('sends the typed question once the answer is done, in the same new chat', async () => {
    /** The question written meanwhile goes out as it stands, in the session the first answer created, with it. */
    server.use(http.get('*/api/sessions/s9', () => HttpResponse.json([])));
    const push = await streaming();
    await userEvent.type(screen.getByPlaceholderText(INPUT), 'And in Uppsala?');
    push({ type: 'response.completed' });
    push({ type: 'done', session_id: 's9' });
    push(null);
    // The page passes the new session back, as onSessionCreated makes it do
    push.view.rerender(createElement(Chat, { sessionId: 's9', onSessionCreated: () => undefined, user: { name: 'anna' } }));
    const sent: { session_id?: string; messages?: { role: string; content: string }[] }[] = [];
    server.use(http.post('*/api/chat/stream', async ({ request }) => {
      sent.push(await request.json() as (typeof sent)[number]);
      return sse({ type: 'done', session_id: 's9' });
    }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].session_id).toBe('s9');
    expect(sent[0].messages?.at(-1)).toEqual({ role: 'user', content: 'And in Uppsala?' });
    expect(sent[0].messages?.some((m) => m.content.includes('The first part.'))).toBe(true);
  });

  it('does not send while a reopened answer is still being checked', async () => {
    /** An answer left to finish in the background (saved as streaming) keeps Send off until it is done. */
    history(answer(2, [CITATIONS], { status: 'streaming' }));
    chat('s1');
    await screen.findByText(CHECKING);

    await userEvent.type(screen.getByPlaceholderText(INPUT), 'And in Uppsala?');

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });
});

describe('scrolling while an answer streams', () => {
  const scrolled = vi.mocked(Element.prototype.scrollIntoView);

  // The reader's place in the conversation: `fromBottom` px above its end (jsdom has no layout)
  function scrollTo(fromBottom: number) {
    const conversation = screen.getByRole('region', { name: 'Conversation' });
    Object.defineProperty(conversation, 'scrollHeight', { configurable: true, value: 3000 });
    Object.defineProperty(conversation, 'clientHeight', { configurable: true, value: 600 });
    conversation.scrollTop = 3000 - 600 - fromBottom;
    fireEvent.scroll(conversation);
  }

  async function streamFirstPart() {
    const push = liveStream();
    chat();
    await ask();
    push({ type: 'session_id', session_id: 's9' });
    push({ type: 'response.output_text.delta', delta: 'The first part.' });
    await screen.findByText(/The first part/);
    return push;
  }

  async function nextPart(push: (event: object) => void, text: string) {
    scrolled.mockClear();
    push({ type: 'response.output_text.delta', delta: ` ${text}` });
    await screen.findByText(new RegExp(text));
  }

  it('leaves the view where the reader scrolled up to', async () => {
    /** Scrolling up during streaming is not undone by the next piece of text. */
    const push = await streamFirstPart();
    scrollTo(1500);

    await nextPart(push, 'The second part.');

    expect(scrolled).not.toHaveBeenCalled();
  });

  it('follows the new text while the reader is at the bottom', async () => {
    /** A reader at the bottom of the conversation sees each new piece of the answer. */
    const push = await streamFirstPart();
    scrollTo(0);

    await nextPart(push, 'The second part.');

    expect(scrolled).toHaveBeenCalled();
  });

  it('follows again once the reader is back at the bottom', async () => {
    /** Scrolling back down to the end makes the chat follow the new text again. */
    const push = await streamFirstPart();
    scrollTo(1500);
    await nextPart(push, 'The second part.');
    scrollTo(0);

    await nextPart(push, 'The third part.');

    expect(scrolled).toHaveBeenCalled();
  });

  it('scrolls down to a question sent while scrolled up', async () => {
    /** Sending a question brings the reader to it even after scrolling up. */
    server.use(
      http.post('*/api/chat/stream', () => sse(
        { type: 'session_id', session_id: 's9' },
        { type: 'response.output_text.delta', delta: 'The first answer.' },
        { type: 'response.completed' },
        { type: 'done', session_id: 's9' },
      )),
      http.get('*/api/sessions/s9', () => HttpResponse.json([])),
    );
    chat();
    await ask();
    await waitFor(() => expect(screen.getByPlaceholderText('Ask about building permits...').closest('form')).toHaveAttribute('aria-busy', 'false'));
    scrollTo(1500);
    liveStream();
    scrolled.mockClear();

    await ask();

    expect(scrolled).toHaveBeenCalled();
  });

  it('opens another saved chat at its latest message after scrolling up', async () => {
    /** A saved chat opened after scrolling up elsewhere still shows its latest message. */
    history(answer(2, []));
    const view = chat('s1');
    await screen.findByText('Do I need bygglov in Ydre?');
    scrollTo(1500);
    server.use(http.get('*/api/sessions/s2', () => HttpResponse.json([
      { id: 5, role: 'user', content: 'Another question', session_id: 's2', created_at: '2026-11-12T11:00:00Z' },
    ])));
    scrolled.mockClear();

    view.rerender(createElement(Chat, { sessionId: 's2', onSessionCreated: () => undefined, user: { name: 'anna' } }));
    await screen.findByText('Another question');

    expect(scrolled).toHaveBeenCalled();
  });
});

// The agent's question card (#91)
const USE = 'What will the building be used for?';
const SIZE = 'Roughly how large will it be?';

const QUESTION = { id: 1, role: 'user', content: 'Can I build a house on my plot?', session_id: 's1',
                   created_at: '2026-11-12T10:00:00Z' };

function card(data: object, content = `${USE}\n${SIZE}`) {
  return { id: 2, role: 'assistant', content, session_id: 's1', created_at: '2026-11-12T10:00:05Z', status: 'done',
           trace: [{ type: 'pipeline', stage: 'choices', data }] };
}

const TWO = card({ questions: [{ question: USE, options: ['A permanent home', 'A holiday home'] },
                               { question: SIZE, options: [] }], offer_pin: false });
const ONE = card({ questions: [{ question: USE, options: ['A permanent home', 'A holiday home'] }], offer_pin: false },
                 USE);

type Sent = { messages: { role: string; content: string }[]; answer_to_question?: boolean };

/** The chat with `history`, recording the next message it sends. */
function chatWith(history: object[]) {
  const sent: { body: Sent | null } = { body: null };
  server.use(
    http.get('*/api/sessions/s1', () => HttpResponse.json(history)),
    http.post('*/api/chat/stream', async ({ request }) => {
      sent.body = (await request.json()) as Sent;
      return sse({ type: 'session_id', session_id: 's1' }, { type: 'done', session_id: 's1' });
    }),
  );
  chat('s1');
  return sent;
}

async function sentReply(sent: { body: Sent | null }) {
  await waitFor(() => expect(sent.body).not.toBeNull());
  return sent.body!;
}

describe('the question card', () => {
  it('shows each question with its own options', async () => {
    chatWith([QUESTION, TWO]);
    const use = await screen.findByRole('group', { name: USE });
    expect(within(use).getByRole('button', { name: 'A permanent home' })).toBeInTheDocument();
    expect(within(use).getByRole('button', { name: 'A holiday home' })).toBeInTheDocument();
  });

  it('shows an open question with only a text field', async () => {
    /** Where a few likely answers do not exist, the question has no option buttons. */
    chatWith([QUESTION, TWO]);
    const size = await screen.findByRole('group', { name: SIZE });
    expect(within(size).queryAllByRole('button')).toHaveLength(0);
    expect(within(size).getByRole('textbox', { name: 'Other' })).toBeInTheDocument();
  });

  it('gives a question with options an "Other" field too', async () => {
    chatWith([QUESTION, TWO]);
    const use = await screen.findByRole('group', { name: USE });
    expect(within(use).getByRole('textbox', { name: 'Other' })).toBeInTheDocument();
  });

  it('sends a clicked option of a single question at once, as the answer to the card', async () => {
    const sent = chatWith([QUESTION, ONE]);
    await userEvent.click(await screen.findByRole('button', { name: 'A permanent home' }));
    const body = await sentReply(sent);
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: 'A permanent home' });
    expect(body.answer_to_question).toBe(true);
  });

  it('sends what is typed in "Other" of a single question', async () => {
    const sent = chatWith([QUESTION, ONE]);
    const use = await screen.findByRole('group', { name: USE });
    await userEvent.type(within(use).getByRole('textbox', { name: 'Other' }), 'A studio for my pottery{Enter}');
    expect((await sentReply(sent)).messages.at(-1)!.content).toBe('A studio for my pottery');
  });

  it('sends the answers to several questions together, one line per question', async () => {
    /** All missing facts go back to the agent in one message. */
    const sent = chatWith([QUESTION, TWO]);
    const use = await screen.findByRole('group', { name: USE });
    await userEvent.click(within(use).getByRole('button', { name: 'A permanent home' }));
    await userEvent.type(within(screen.getByRole('group', { name: SIZE })).getByRole('textbox', { name: 'Other' }),
                         'About 120 m²');
    await userEvent.click(screen.getByRole('button', { name: 'Send answer' }));
    const body = await sentReply(sent);
    expect(body.messages.at(-1)!.content).toBe(`${USE} A permanent home\n${SIZE} About 120 m²`);
    expect(body.answer_to_question).toBe(true);
  });

  it('does not send several questions on the first click', async () => {
    /** With more than one question, picking an option only selects it. */
    const sent = chatWith([QUESTION, TWO]);
    const use = await screen.findByRole('group', { name: USE });
    await userEvent.click(within(use).getByRole('button', { name: 'A permanent home' }));
    expect(sent.body).toBeNull();
  });

  it('cannot send the card before any question has an answer', async () => {
    chatWith([QUESTION, TWO]);
    await screen.findByRole('group', { name: USE });
    expect(screen.getByRole('button', { name: 'Send answer' })).toBeDisabled();
  });

  it('leaves an unanswered question out of the reply', async () => {
    /** The user may answer only part of the card; the agent then states assumptions for the rest. */
    const sent = chatWith([QUESTION, TWO]);
    const use = await screen.findByRole('group', { name: USE });
    await userEvent.click(within(use).getByRole('button', { name: 'A holiday home' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send answer' }));
    expect((await sentReply(sent)).messages.at(-1)!.content).toBe(`${USE} A holiday home`);
  });

  it('counts a message typed in the chat input as the answer to an open card', async () => {
    /** "Just answer" typed below the card must not get the same question again. */
    const sent = chatWith([QUESTION, TWO]);
    await screen.findByRole('group', { name: USE });
    await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'Just answer{Enter}');
    expect((await sentReply(sent)).answer_to_question).toBe(true);
  });

  it('offers to pin the place from a card that asks for it', async () => {
    chatWith([QUESTION, card({ questions: [{ question: 'Which plot do you mean?', options: [] }], offer_pin: true },
                             'Which plot do you mean?')]);
    await screen.findByRole('group', { name: 'Which plot do you mean?' });
    expect(screen.getByRole('button', { name: 'Pin it on the map' })).toBeInTheDocument();
  });

  it('keeps an answered card, locked, with the reply', async () => {
    /** Once answered, the card still shows its questions and what the user replied, and takes no input. */
    chatWith([QUESTION, TWO,
              { id: 3, role: 'user', content: `${USE} A holiday home`, session_id: 's1',
                created_at: '2026-11-12T10:01:00Z' },
              { id: 4, role: 'assistant', content: 'A holiday home needs bygglov.', session_id: 's1',
                created_at: '2026-11-12T10:01:30Z', status: 'done', trace: [] }]);
    const use = await screen.findByRole('group', { name: USE });
    expect(within(use).queryAllByRole('button')).toHaveLength(0);
    expect(within(use).queryAllByRole('textbox')).toHaveLength(0);
    expect(within(screen.getByRole('region', { name: 'Questions for you' })).getByText(/A holiday home/))
      .toBeInTheDocument();
  });

  it('still shows a question saved before the card, as one question', async () => {
    /** Older chats saved only the options; the message itself is the question. */
    chatWith([QUESTION, card({ options: ['A permanent home', 'A holiday home'] }, USE)]);
    const use = await screen.findByRole('group', { name: USE });
    expect(within(use).getByRole('button', { name: 'A permanent home' })).toBeInTheDocument();
  });
});

// --- the claim check runs while the reader carries on (#137) ----------------------------------------

const CHECKING = 'Checking the claims';
const CHECK_FLAGGED = { status: 'checked', claims: [
  HOUSE_SUPPORTED, { text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [FEE] }] };
const CHECK_FAILED = { status: 'failed', claims: [] };

// The events of an answer up to the start of its check: the text is complete, the check result is still to come
const UNTIL_CHECK = [
  { type: 'session_id', session_id: 's1' },
  { type: 'response.output_text.delta', delta: ANSWER },
  { type: 'pipeline', ...CITATIONS },
  { type: 'thinking', label: CHECKING },
];
const result = (data: object) => [
  { type: 'pipeline', stage: 'claim_check', data },
  { type: 'response.completed' },
  { type: 'done', session_id: 's1' },
];

// A stream the test feeds as it goes: the events given first, more with push, the end with push(..., close)
function fedStream(...first: object[]) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const encode = (event: object) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);
  const body = new ReadableStream<Uint8Array>({
    start(started) {
      controller = started;
      first.forEach((event) => controller.enqueue(encode(event)));
    },
  });
  return {
    response: () => new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    push: (...events: object[]) => events.forEach((event) => controller.enqueue(encode(event))),
    close: () => controller.close(),
  };
}

// Each question sent gets the next of `streams`
function answerWith(...streams: ReturnType<typeof fedStream>[]) {
  let sent = 0;
  server.use(http.post('*/api/chat/stream', () => streams[sent++].response()));
  return () => sent;
}

describe('sending while an answer is checked', () => {
  it('lets the next question be sent once the answer text is finished', async () => {
    /** The check of an answer does not hold the next question back. */
    answerWith(fedStream(...UNTIL_CHECK));
    chat();
    await ask();
    await screen.findByText(CHECKING);

    await userEvent.type(screen.getByPlaceholderText('Ask about building permits...'), 'And the fee?');
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
  });

  it('sends the next question while the earlier answer is checked', async () => {
    /** A question sent during the check reaches the server. */
    const sent = answerWith(fedStream(...UNTIL_CHECK), fedStream({ type: 'session_id', session_id: 's1' }));
    chat();
    await ask();
    await screen.findByText(CHECKING);

    await ask('And the fee?');
    await waitFor(() => expect(sent()).toBe(2));
  });

  it('puts the check result on the earlier answer when a later one is streaming', async () => {
    /** A result that arrives after the next question was sent lands on the answer it checked. */
    const first = fedStream(...UNTIL_CHECK);
    const second = fedStream({ type: 'session_id', session_id: 's1' },
                              { type: 'response.output_text.delta', delta: 'The second answer' });
    answerWith(first, second);
    chat();
    await ask();
    await screen.findByText(CHECKING);
    await ask('And the fee?');
    await screen.findByText('The second answer');

    first.push(...result(CHECK_FLAGGED));
    first.close();

    await userEvent.hover(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    const tinted = [...document.querySelectorAll('[data-tinted="true"]')].map((element) => element.textContent);
    expect(tinted).toEqual([FEE]);
    expect(screen.getByText('The second answer')).toBeInTheDocument();
  });

  it('keeps writing the later answer after the earlier check has landed', async () => {
    /** The later answer goes on streaming into its own message once the earlier result is in. */
    const first = fedStream(...UNTIL_CHECK);
    const second = fedStream({ type: 'session_id', session_id: 's1' },
                              { type: 'response.output_text.delta', delta: 'The second' });
    answerWith(first, second);
    chat();
    await ask();
    await screen.findByText(CHECKING);
    await ask('And the fee?');
    await screen.findByText('The second');

    first.push(...result(CHECK_FLAGGED));
    first.close();
    await screen.findByRole('button', { name: MAY_NOT_BACK });
    second.push({ type: 'response.output_text.delta', delta: ' answer goes on' });

    expect(await screen.findByText('The second answer goes on')).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(FEE))).toHaveLength(1);
  });
});

describe('the status line of an answer being checked', () => {
  it('pulses on the answer while its claims are checked', async () => {
    /** A discreet line that pulses says the check is running, with no spinner. */
    answerWith(fedStream(...UNTIL_CHECK));
    chat();
    await ask();

    const line = await screen.findByText(CHECKING);
    expect(line.className).toContain('animate-pulse');
    expect(line.parentElement?.querySelector('.animate-spin')).toBeNull();
  });

  it('is in Swedish on the Swedish page', async () => {
    /** The status line follows the page language. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    answerWith(fedStream(...UNTIL_CHECK));
    chat();
    await userEvent.type(screen.getByRole('textbox'), 'Behöver jag bygglov i Ydre?');
    await userEvent.click(screen.getByRole('button', { name: 'Skicka' }));

    expect(await screen.findByText('Kontrollerar påståendena')).toBeInTheDocument();
  });

  it('goes away when the check is done and its result shows', async () => {
    /** With nothing sent meanwhile, the result replaces the status line. */
    const stream = fedStream(...UNTIL_CHECK);
    answerWith(stream);
    chat();
    await ask();
    await screen.findByText(CHECKING);

    stream.push(...result(CHECK_FLAGGED));
    stream.close();

    expect(await screen.findByRole('button', { name: MAY_NOT_BACK })).toBeInTheDocument();
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });

  it('stays on the earlier answer while a later one streams', async () => {
    /** Sending the next question does not end the earlier answer's status line. */
    answerWith(fedStream(...UNTIL_CHECK), fedStream({ type: 'session_id', session_id: 's1' },
                                                       { type: 'response.output_text.delta', delta: 'The second answer' }));
    chat();
    await ask();
    await screen.findByText(CHECKING);
    await ask('And the fee?');
    await screen.findByText('The second answer');

    expect(screen.getByText(CHECKING)).toBeInTheDocument();
  });

  it('pulses on an answer still being checked when its chat is reopened', async () => {
    /** A chat reopened during the check shows the pulsing line on that answer. */
    history(answer(2, [CITATIONS], { status: 'streaming' }));
    chat('s1');

    expect((await screen.findByText(CHECKING)).className).toContain('animate-pulse');
  });

  it('gives way to the result of a reopened answer once its check is done', async () => {
    /** The reopened answer gets its result without a reload by the reader. */
    history(answer(2, [CITATIONS], { status: 'streaming' }));
    chat('s1');
    await screen.findByText(CHECKING);

    history(answer(2, [CITATIONS, { stage: 'claim_check', data: CHECK_FLAGGED }]));

    expect(await screen.findByRole('button', { name: MAY_NOT_BACK }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });

  it('is absent from an answer saved before the check existed', async () => {
    /** An old answer without a check result shows no status line. */
    history(answer(2, [CITATIONS]));
    chat('s1');

    await screen.findByText(new RegExp(FEE));
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
    expect(screen.queryByText('Checking claims…')).not.toBeInTheDocument();
  });
});

describe('a check that could not run', () => {
  it('leaves a grey line in place of the status line', async () => {
    /** A failed check says so in grey, not amber, and the status line goes away. */
    const stream = fedStream(...UNTIL_CHECK);
    answerWith(stream);
    chat();
    await ask();
    await screen.findByText(CHECKING);

    stream.push(...result(CHECK_FAILED));
    stream.close();

    const notice = await screen.findByText(NOTICE);
    expect(notice.className).not.toContain('amber');
    expect(notice.className).toContain('zinc');
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });
});
