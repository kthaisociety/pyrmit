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

describe('a flagged claim says what its marking means', () => {
  const FLAGGED = () => history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED,
    { text: FEE, verdict: 'uncited', chunk_ids: [], supporting: [] })]));

  it('explains the dotted underline under an answer with a flagged claim', async () => {
    /** One line under the answer says that underlined text could not be confirmed by the sources (#105). */
    FLAGGED();
    chat('s1');

    expect(await screen.findByText(/Text with a dotted underline could not be confirmed by the sources/)).toBeInTheDocument();
  });

  it('gives no explanation when no claim is flagged', async () => {
    /** An answer whose claims are all supported carries no note about markings. */
    history(answer(2, [CITATIONS, checked(HOUSE_SUPPORTED)]));
    chat('s1');

    await screen.findByText(new RegExp(HOUSE));
    expect(screen.queryByText(/dotted underline/)).not.toBeInTheDocument();
  });

  it('shows the reason in the text when the warning sign is pressed', async () => {
    /** The ⚠ after a flagged claim shows its reason on a press, so a touch screen gets it too. */
    FLAGGED();
    chat('s1');

    await userEvent.click(await screen.findByRole('button', { name: 'Why is this marked?' }));
    expect(screen.getByText('(No source cited)')).toBeInTheDocument();
  });

  it('marks a flagged claim with a dotted underline, not a highlight', async () => {
    /** The marking reads as unconfirmed, not as a spelling error: a dotted underline and no background. */
    FLAGGED();
    chat('s1');

    const mark = await screen.findByTitle(NO_SOURCE);
    expect(mark.className).toContain('decoration-dotted');
    expect(mark.className).not.toContain('decoration-wavy');
  });

  it('gives the reason in Swedish on the Swedish page', async () => {
    /** The reason and the note follow the page language. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    FLAGGED();
    chat('s1');

    expect(await screen.findByTitle('Ingen källa angiven')).toHaveTextContent(FEE);
    expect(screen.getByText(/Text med prickad understrykning kunde inte bekräftas av källorna/)).toBeInTheDocument();
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

describe('scrolling while an answer streams', () => {
  const scrolled = vi.mocked(Element.prototype.scrollIntoView);

  // A stream whose deltas the test sends one at a time
  function liveStream() {
    let push: (event: object) => void = () => {};
    server.use(http.post('*/api/chat/stream', () => {
      const body = new ReadableStream({
        start(controller) {
          push = (event) => controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
        },
      });
      return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } });
    }));
    return (event: object) => push(event);
  }

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
    await waitFor(() => expect(screen.getByPlaceholderText('Ask about building permits...')).toBeEnabled());
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
