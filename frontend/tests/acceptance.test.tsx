// Acceptance tests of issue #137: the claim check runs while the reader carries on.
// Lives only on the issue's branch; folded into tests/unit/components/Chat.test.tsx before the branch merges.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import { LANGUAGE_STORAGE_KEY, LanguageProvider } from '@/lib/i18n';

import { server } from './mocks/server';

// jsdom has no layout: the chat scrolls to its last message on render
Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/components/place/PlaceMap', () => ({ default: () => createElement('div', { 'data-testid': 'map' }) }));

const B = 'b'.repeat(16);
const FEE = 'The fee is 12 000 kr';
const SOURCES = '\n\n---\n**Sources**\n- [1] Ydre – Bygglovstaxa';
const ANSWER = `${FEE} [1].${SOURCES}`;
const CHECKING = 'Checking the claims';
const MAY_NOT_BACK = 'The sources may not back this claim';
const NOTICE = 'The claims in this answer could not be checked.';
const INPUT = 'Ask about building permits...';

const CITATIONS = {
  stage: 'citations',
  data: { items: [{ n: 1, label: 'Ydre – Bygglovstaxa', chunks: [{ source: 'Ydre – Bygglovstaxa', chunk_id: B, content: 'Taxa.' }] }] },
};
const FLAGGED = { status: 'checked', claims: [{ text: FEE, verdict: 'unsupported', chunk_ids: [B], supporting: [], unbacked: [FEE] }] };
const FAILED = { status: 'failed', claims: [] };

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
function liveStream(...first: object[]) {
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
function answerWith(...streams: ReturnType<typeof liveStream>[]) {
  let sent = 0;
  server.use(http.post('*/api/chat/stream', () => streams[sent++].response()));
  return () => sent;
}

function chat(sessionId: string | null = null) {
  return render(createElement(Chat, { sessionId, onSessionCreated: () => undefined, user: { name: 'anna' } }),
    { wrapper: LanguageProvider });
}

async function ask(question = 'Do I need bygglov in Ydre?') {
  await userEvent.type(screen.getByPlaceholderText(INPUT), question);
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));
}

function saved(extra: object) {
  server.use(http.get('*/api/sessions/s1', () => HttpResponse.json([
    { id: 1, role: 'user', content: 'Do I need bygglov in Ydre?', session_id: 's1', created_at: '2026-11-12T10:00:00Z' },
    { id: 2, role: 'assistant', content: ANSWER, session_id: 's1', created_at: '2026-11-12T10:00:05Z', ...extra },
  ])));
}

describe('sending while an answer is checked', () => {
  it('lets the next question be sent once the answer text is finished', async () => {
    /** The check of an answer does not hold the next question back. */
    answerWith(liveStream(...UNTIL_CHECK));
    chat();
    await ask();
    await screen.findByText(CHECKING);

    await userEvent.type(screen.getByPlaceholderText(INPUT), 'And the fee?');
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
  });

  it('sends the next question while the earlier answer is checked', async () => {
    /** A question sent during the check reaches the server. */
    const sent = answerWith(liveStream(...UNTIL_CHECK), liveStream({ type: 'session_id', session_id: 's1' }));
    chat();
    await ask();
    await screen.findByText(CHECKING);

    await ask('And the fee?');
    await waitFor(() => expect(sent()).toBe(2));
  });

  it('puts the check result on the earlier answer when a later one is streaming', async () => {
    /** A result that arrives after the next question was sent lands on the answer it checked. */
    const first = liveStream(...UNTIL_CHECK);
    const second = liveStream({ type: 'session_id', session_id: 's1' },
                              { type: 'response.output_text.delta', delta: 'The second answer' });
    answerWith(first, second);
    chat();
    await ask();
    await screen.findByText(CHECKING);
    await ask('And the fee?');
    await screen.findByText('The second answer');

    first.push(...result(FLAGGED));
    first.close();

    await userEvent.hover(await screen.findByRole('button', { name: MAY_NOT_BACK }));
    const tinted = [...document.querySelectorAll('[data-tinted="true"]')].map((element) => element.textContent);
    expect(tinted).toEqual([FEE]);
    expect(screen.getByText('The second answer')).toBeInTheDocument();
  });

  it('keeps writing the later answer after the earlier check has landed', async () => {
    /** The later answer goes on streaming into its own message once the earlier result is in. */
    const first = liveStream(...UNTIL_CHECK);
    const second = liveStream({ type: 'session_id', session_id: 's1' },
                              { type: 'response.output_text.delta', delta: 'The second' });
    answerWith(first, second);
    chat();
    await ask();
    await screen.findByText(CHECKING);
    await ask('And the fee?');
    await screen.findByText('The second');

    first.push(...result(FLAGGED));
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
    answerWith(liveStream(...UNTIL_CHECK));
    chat();
    await ask();

    const line = await screen.findByText(CHECKING);
    expect(line.className).toContain('animate-pulse');
    expect(line.parentElement?.querySelector('.animate-spin')).toBeNull();
  });

  it('is in Swedish on the Swedish page', async () => {
    /** The status line follows the page language. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    answerWith(liveStream(...UNTIL_CHECK));
    chat();
    await userEvent.type(screen.getByRole('textbox'), 'Behöver jag bygglov i Ydre?');
    await userEvent.click(screen.getByRole('button', { name: 'Skicka' }));

    expect(await screen.findByText('Kontrollerar påståendena')).toBeInTheDocument();
  });

  it('goes away when the check is done and its result shows', async () => {
    /** With nothing sent meanwhile, the result replaces the status line. */
    const stream = liveStream(...UNTIL_CHECK);
    answerWith(stream);
    chat();
    await ask();
    await screen.findByText(CHECKING);

    stream.push(...result(FLAGGED));
    stream.close();

    expect(await screen.findByRole('button', { name: MAY_NOT_BACK })).toBeInTheDocument();
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });

  it('stays on the earlier answer while a later one streams', async () => {
    /** Sending the next question does not end the earlier answer's status line. */
    answerWith(liveStream(...UNTIL_CHECK), liveStream({ type: 'session_id', session_id: 's1' },
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
    saved({ status: 'streaming', trace: [CITATIONS] });
    chat('s1');

    expect((await screen.findByText(CHECKING)).className).toContain('animate-pulse');
  });

  it('gives way to the result of a reopened answer once its check is done', async () => {
    /** The reopened answer gets its result without a reload by the reader. */
    saved({ status: 'streaming', trace: [CITATIONS] });
    chat('s1');
    await screen.findByText(CHECKING);

    saved({ status: 'done', trace: [CITATIONS, { stage: 'claim_check', data: FLAGGED }] });

    expect(await screen.findByRole('button', { name: MAY_NOT_BACK }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });

  it('is absent from an answer saved before the check existed', async () => {
    /** An old answer without a check result shows no status line. */
    saved({ status: 'done', trace: [CITATIONS] });
    chat('s1');

    await screen.findByText(new RegExp(FEE));
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
    expect(screen.queryByText('Checking claims…')).not.toBeInTheDocument();
  });
});

describe('a check that could not run', () => {
  it('leaves a grey line in place of the status line', async () => {
    /** A failed check says so in grey, not amber, and the status line goes away. */
    const stream = liveStream(...UNTIL_CHECK);
    answerWith(stream);
    chat();
    await ask();
    await screen.findByText(CHECKING);

    stream.push(...result(FAILED));
    stream.close();

    const notice = await screen.findByText(NOTICE);
    expect(notice.className).not.toContain('amber');
    expect(notice.className).toContain('zinc');
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument();
  });
});
