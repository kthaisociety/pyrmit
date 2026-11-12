// Acceptance tests of issue #83: when the cited passage is not found in the PDF, the viewer says so instead of
// silently opening page 1, and opens the PDF from page 1 only when asked.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SourceViewer, { Citation } from '@/components/SourceViewer';

import { server } from './mocks/server';

const citation: Citation = {
  n: 1,
  label: 'Vallentuna – Detaljplan Kårsta',
  chunks: [{ chunk_id: 'c1', source: 'Detaljplan Kårsta', chunk_index: 3, content: 'Nockhöjd 8 m', doc_id: 'pdf:0115:aa' }],
};
// What locate answers when the chunk's wording is on no page of the PDF
const notFound = { type: 'pdf', page: 1, found: false, highlighted: false, pdf_url: '/api/docs/pdf/c1', view: null };
const NOT_FOUND = 'The cited passage was not found in this PDF.';
const OPEN_FROM_PAGE_1 = /Open the PDF from page 1/;

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:pdf', revokeObjectURL: () => {} }));
  server.use(
    http.get('*/api/docs/locate', () => HttpResponse.json(notFound)),
    http.get('*/api/docs/pdf/c1', () =>
      new HttpResponse('%PDF-1.7', { status: 200, headers: { 'Content-Type': 'application/pdf' } })),
  );
});

const openThePassage = async () => {
  render(createElement(SourceViewer, { citation, onClose: vi.fn() }));
  await userEvent.click(screen.getByRole('button', { name: /Open the PDF at this passage/ }));
};

describe('SourceViewer, passage not found', () => {
  it('says the cited passage was not found in the PDF', async () => {
    /** locate found the wording on no page: the viewer says so in plain words. */
    await openThePassage();

    expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
  });

  it('does not open the PDF on its own when the passage was not found', async () => {
    /** Page 1 holds nothing the citation points at: no PDF is shown until the user asks for it. */
    await openThePassage();
    await screen.findByRole('button', { name: OPEN_FROM_PAGE_1 });

    expect(screen.queryByTitle(citation.label)).not.toBeInTheDocument();
  });

  it('opens the PDF from page 1 when asked after the passage was not found', async () => {
    /** The notice offers the whole document anyway, from its first page. */
    await openThePassage();
    await userEvent.click(await screen.findByRole('button', { name: OPEN_FROM_PAGE_1 }));

    const viewer = await screen.findByTitle(citation.label);
    expect(viewer.getAttribute('src')).toContain('#page=1');
  });
});
