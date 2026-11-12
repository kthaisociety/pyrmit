// Acceptance tests for issue #84: the source panel underlines the sentences that back the answer's claims.
// Temporary: folded into the module test files before the branch merges.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Chat from '@/components/Chat';
import SourceViewer, { type Citation } from '@/components/SourceViewer';

import { server } from './mocks/server';

// jsdom has no layout: the chat scrolls to its last message on render
Element.prototype.scrollIntoView = vi.fn();

const UNDERLINED = 'Supports a claim in the answer';

const A = 'a'.repeat(16);
const B = 'b'.repeat(16);
const NEEDED = 'Bygglov krävs för en ny byggnad.';
const HEIGHT = 'Byggnadshöjden får vara högst 8 meter.';
const CHUNK_A = `${NEEDED} Ansökan lämnas till byggnadsnämnden. ${HEIGHT}`;
const HOUSE = 'Bygglov is needed for a new house';
const TALL = 'The house may be at most 8 m high';
const ANSWER = `${HOUSE} [1]. ${TALL} [1].\n\n---\n**Sources**\n- [1] PBL, 9 kap. 2 §`;

const CITATIONS = {
  stage: 'citations',
  data: { items: [{ n: 1, label: 'PBL, 9 kap. 2 §', chunks: [{ source: 'PBL, 9 kap. 2 §', chunk_id: A, content: CHUNK_A }] }] },
};

function supported(text: string, sentence: string) {
  return { text, verdict: 'supported', chunk_ids: [A], supporting: [{ chunk_id: A, sentence }] };
}

function checked(...claims: object[]) {
  return { stage: 'claim_check', data: { status: 'checked', claims } };
}

const FAILED = { stage: 'claim_check', data: { status: 'failed', claims: [] } };

function history(trace: object[]) {
  server.use(http.get('*/api/sessions/s1', () => HttpResponse.json([
    { id: 1, role: 'user', content: 'Do I need bygglov?', session_id: 's1', created_at: '2026-11-12T10:00:00Z' },
    { id: 2, role: 'assistant', content: ANSWER, session_id: 's1', created_at: '2026-11-12T10:00:05Z',
      status: 'done', trace },
  ])));
}

async function openChip() {
  render(createElement(Chat, { sessionId: 's1', onSessionCreated: () => undefined, user: { name: 'anna' } }));
  await userEvent.click((await screen.findAllByRole('button', { name: '1' }))[0]);
}

function underlined(): (string | null)[] {
  return screen.queryAllByTitle(UNDERLINED).map((element) => element.textContent);
}

describe('the panel a citation chip opens', () => {
  it('underlines the sentence of the cited chunk that backs a claim', async () => {
    /** After the check, the chip's panel underlines the chunk sentence that supports the claim. */
    history([CITATIONS, checked(supported(HOUSE, NEEDED))]);
    await openChip();

    expect(underlined()).toEqual([NEEDED]);
  });

  it('underlines the sentences of every claim that cites the chunk', async () => {
    /** A chunk cited by two claims underlines the supporting sentence of each. */
    history([CITATIONS, checked(supported(HOUSE, NEEDED), supported(TALL, HEIGHT))]);
    await openChip();

    expect(underlined()).toEqual([NEEDED, HEIGHT]);
  });

  it('shows the chunk without underline for an answer saved before the check', async () => {
    /** An old message with no check result opens its chunk with nothing underlined. */
    history([CITATIONS]);
    await openChip();

    expect(underlined()).toEqual([]);
  });

  it('shows the chunk without underline when the check failed', async () => {
    /** A failed check has no supporting sentences, so nothing in the chunk is underlined. */
    history([CITATIONS, FAILED]);
    await openChip();

    expect(underlined()).toEqual([]);
  });
});

describe('SourceViewer with supporting sentences', () => {
  const citation: Citation = {
    n: 1,
    label: 'Detaljplan Kårsta',
    chunks: [
      { chunk_id: A, source: 'Detaljplan Kårsta', chunk_index: 3, content: 'Nockhöjden får vara\nhögst 8 m. Taket ska vara rött.' },
      { chunk_id: B, source: 'Detaljplan Kårsta', chunk_index: 4, content: 'Taket ska vara rött. Fasaden är av trä.' },
    ],
  };

  it('underlines a sentence whose line breaks differ from the chunk text', () => {
    /** Whitespace in the supporting sentence need not match the chunk's line breaks. */
    render(createElement(SourceViewer, { citation, onClose: vi.fn(), supporting: { [A]: ['Nockhöjden får vara högst 8 m.'] } }));

    expect(underlined().map((text) => text?.replace(/\s+/g, ' '))).toEqual(['Nockhöjden får vara högst 8 m.']);
  });

  it('skips a supporting sentence that is not in the chunk', () => {
    /** A sentence the chunk does not hold is left out without an error; the ones it holds are underlined. */
    render(createElement(SourceViewer, {
      citation, onClose: vi.fn(), supporting: { [A]: ['Byggrätten är 200 kvm.', 'Taket ska vara rött.'] },
    }));

    expect(underlined()).toEqual(['Taket ska vara rött.']);
  });

  it('underlines a sentence only in the chunk it supports', () => {
    /** Two chunks hold the same sentence; only the chunk the claim cites underlines it. */
    render(createElement(SourceViewer, { citation, onClose: vi.fn(), supporting: { [B]: ['Taket ska vara rött.'] } }));

    expect(underlined()).toEqual(['Taket ska vara rött.']);
  });
});
