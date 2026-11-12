// Acceptance tests of #91: the agent's question card in the chat. Folded into tests/unit/ before merge.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import { LanguageProvider } from '@/lib/i18n';

import { server } from './mocks/server';

Element.prototype.scrollIntoView = vi.fn();

vi.mock('@/components/place/PlaceMap', () => ({
  default: () => createElement('div', { 'data-testid': 'map' }),
}));

const USE = 'What will the building be used for?';
const SIZE = 'Roughly how large will it be?';

function chat(sessionId: string) {
  return render(createElement(Chat, { sessionId, onSessionCreated: () => undefined, user: { name: 'anna' } }),
                { wrapper: LanguageProvider });
}

function sse(...events: object[]) {
  return new HttpResponse(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

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
