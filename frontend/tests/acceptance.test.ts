// Acceptance tests of issue #82: claims the sources do not back are flagged in the answer, a check that could not
// run gets a notice, and the answer shows that its claims are being checked until they are.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';

import { server } from './mocks/server';

// Each test renders the whole chat and waits for its history: slower than the default 5 s on a busy runner
vi.setConfig({ testTimeout: 15_000 });

// jsdom has no layout: the chat scrolls to its last message on render
Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/components/place/PlaceMap', () => ({ default: () => createElement('div', { 'data-testid': 'map' }) }));

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

function chat(sessionId: string | null = null) {
  return render(createElement(Chat, { sessionId, onSessionCreated: () => undefined, user: { name: 'anna' } }));
}

function sse(...events: object[]) {
  return new HttpResponse(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream' },
  });
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

describe('flags on claims the sources do not back', () => {
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
    expect(screen.getByText(new RegExp(HOUSE))).toBeInTheDocument();
  });
});
