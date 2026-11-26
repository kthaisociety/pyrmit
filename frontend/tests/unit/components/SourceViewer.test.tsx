// Component tests for components/SourceViewer.tsx.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SourceViewer, { Citation } from '@/components/SourceViewer';
import { LanguageProvider } from '@/lib/i18n';

import { server } from '../../mocks/server';

const citation: Citation = {
  n: 1,
  label: 'Vallentuna – Detaljplan Kårsta',
  chunks: [{ chunk_id: 'c1', source: 'Detaljplan Kårsta', chunk_index: 3, content: 'Nockhöjd 8 m', doc_id: 'pdf:0115:aa' }],
};
const located = { type: 'pdf', page: 3, found: true, highlighted: true, pdf_url: '/api/docs/pdf/c1', view: null };
// The chunk's wording is on no page of the PDF
const notFound = { ...located, page: 1, found: false, highlighted: false };
const NOT_FOUND = 'The cited passage was not found in this PDF.';
const OPEN_FROM_PAGE_1 = /Open the PDF from page 1/;
const OPENED = 'Page 3, cited passage highlighted.';

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:pdf', revokeObjectURL: () => {} }));
  // A string body: jsdom's Blob has no stream() on Node 22, which made MSW fail the request in CI
  server.use(http.get('*/api/docs/pdf/c1', () =>
    new HttpResponse('%PDF-1.7', { status: 200, headers: { 'Content-Type': 'application/pdf' } })));
});

const openThePassage = async (shown: Citation = citation) => {
  render(<SourceViewer citation={shown} onClose={vi.fn()} />, { wrapper: LanguageProvider });
  await userEvent.click(screen.getAllByRole('button', { name: /Open the PDF at this passage/ })[0]);
};

// Corpus on Neon: the first opening fetches the PDF from the kommun's website, which takes seconds.
// Returns what lets the download finish.
const downloadFirst = (): (() => void) => {
  let finishDownload: () => void = () => {};
  const downloaded = new Promise<void>((resolve) => { finishDownload = resolve; });
  server.use(
    http.get('*/api/docs/locate', async ({ request }) => {
      if (new URL(request.url).searchParams.get('download') === 'false') {
        return HttpResponse.json({ type: 'pdf', needs_download: true, source_host: 'www.vallentuna.se' });
      }
      await downloaded;
      return HttpResponse.json(located);
    }),
  );
  return finishDownload;
};

const legacy: Citation = {
  n: 2,
  label: 'Vallentuna – Översiktsplan 2040',
  chunks: [
    { chunk_id: 'l1', source: 'Översiktsplan 2040', chunk_index: 0, content: 'Vision', doc_id: 'legacy:2040vision', url: null },
    { chunk_id: 's1', source: 'PBL', chunk_index: 1, content: '4 §', doc_id: 'law:pbl', url: 'https://data.riksdagen.se/a' },
  ],
};

describe('SourceViewer', () => {
  describe('a PDF this install must first download', () => {
    it('says it is being downloaded from the kommun site', async () => {
      downloadFirst();
      await openThePassage();

      expect(await screen.findByRole('status')).toHaveTextContent('Downloading the PDF from www.vallentuna.se');
    });

    it('opens at the passage once downloaded', async () => {
      const finishDownload = downloadFirst();
      await openThePassage();
      await screen.findByRole('status');
      finishDownload();

      expect(await screen.findByText(OPENED)).toBeInTheDocument();
    });

    it('drops the download message once open', async () => {
      const finishDownload = downloadFirst();
      await openThePassage();
      await screen.findByRole('status');
      finishDownload();
      await screen.findByText(OPENED);

      expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
  });

  describe('a document kept without its original', () => {
    /** The early prototype's "legacy:" documents have no file or URL: a button would only end in an error. */
    it('offers no open button', () => {
      render(<SourceViewer citation={legacy} onClose={vi.fn()} />, { wrapper: LanguageProvider });

      expect(screen.getAllByRole('button', { name: /Open the/ })).toHaveLength(1); // the statute only
    });

    it('says no original was kept', () => {
      render(<SourceViewer citation={legacy} onClose={vi.fn()} />, { wrapper: LanguageProvider });

      expect(screen.getByText(/No original kept/)).toBeInTheDocument();
    });
  });

  describe('while one document opens', () => {
    const two: Citation = { ...citation, chunks: [citation.chunks[0], { ...citation.chunks[0], chunk_id: 'c2' }] };

    beforeEach(() => {
      server.use(http.get('*/api/docs/locate', () => new Promise(() => {}))); // never answers
    });

    it('makes its button wait', async () => {
      await openThePassage(two);

      expect(screen.getAllByRole('button', { name: /Open the PDF at this passage/ })[0]).toBeDisabled();
    });

    it('keeps the other buttons usable', async () => {
      await openThePassage(two);

      expect(screen.getAllByRole('button', { name: /Open the PDF at this passage/ })[1]).toBeEnabled();
    });
  });

  describe('a PDF already on this machine', () => {
    /** The crawl folder or the cache has it: one locate call, straight to the page. */
    let asked: string[];

    beforeEach(() => {
      asked = [];
      server.use(
        http.get('*/api/docs/locate', ({ request }) => {
          asked.push(new URL(request.url).search);
          return HttpResponse.json(located);
        }),
      );
    });

    it('opens at the passage', async () => {
      await openThePassage();

      expect(await screen.findByText(OPENED)).toBeInTheDocument();
    });

    it('opens without a download message', async () => {
      await openThePassage();
      await screen.findByText(OPENED);

      expect(screen.queryByText(/Downloading/)).not.toBeInTheDocument();
    });

    it('is located with one call that downloads nothing', async () => {
      await openThePassage();
      await screen.findByText(OPENED);

      expect(asked).toEqual(['?chunk_id=c1&download=false']);
    });
  });

  describe('a passage not found in its PDF', () => {
    beforeEach(() => {
      server.use(http.get('*/api/docs/locate', () => HttpResponse.json(notFound)));
    });

    it('is reported as not found', async () => {
      await openThePassage();

      expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
    });

    it('does not open the PDF on its own', async () => {
      /** Page 1 holds nothing the citation points at: no PDF is shown until the user asks for it. */
      await openThePassage();
      await screen.findByRole('button', { name: OPEN_FROM_PAGE_1 });

      expect(screen.queryByTitle(citation.label)).not.toBeInTheDocument();
    });

    it('opens the PDF from page 1 when asked', async () => {
      await openThePassage();
      await userEvent.click(await screen.findByRole('button', { name: OPEN_FROM_PAGE_1 }));

      expect((await screen.findByTitle(citation.label)).getAttribute('src')).toContain('#page=1');
    });
  });
});

describe('SourceViewer with supporting sentences', () => {
  const UNDERLINED = 'Supports a claim in the answer';
  const twoChunks: Citation = {
    n: 1,
    label: 'Detaljplan Kårsta',
    chunks: [
      { chunk_id: 'c1', source: 'Detaljplan Kårsta', chunk_index: 3, content: 'Nockhöjden får vara\nhögst 8 m. Taket ska vara rött.' },
      { chunk_id: 'c2', source: 'Detaljplan Kårsta', chunk_index: 4, content: 'Taket ska vara rött. Fasaden är av trä.' },
    ],
  };

  function underlined(): (string | null)[] {
    return screen.queryAllByTitle(UNDERLINED).map((element) => element.textContent);
  }

  it('underlines a sentence whose line breaks differ from the chunk text', () => {
    /** Whitespace in the supporting sentence need not match the chunk's line breaks. */
    render(<SourceViewer citation={twoChunks} onClose={vi.fn()} supporting={{ c1: ['Nockhöjden får vara högst 8 m.'] }} />,
      { wrapper: LanguageProvider });

    expect(underlined().map((text) => text?.replace(/\s+/g, ' '))).toEqual(['Nockhöjden får vara högst 8 m.']);
  });

  it('skips a supporting sentence that is not in the chunk', () => {
    /** A sentence the chunk does not hold is left out without an error; the ones it holds are underlined. */
    render(<SourceViewer citation={twoChunks} onClose={vi.fn()}
      supporting={{ c1: ['Byggrätten är 200 kvm.', 'Taket ska vara rött.'] }} />, { wrapper: LanguageProvider });

    expect(underlined()).toEqual(['Taket ska vara rött.']);
  });

  it('underlines a sentence only in the chunk it supports', () => {
    /** Two chunks hold the same sentence; only the chunk the claim cites underlines it. */
    render(<SourceViewer citation={twoChunks} onClose={vi.fn()} supporting={{ c2: ['Taket ska vara rött.'] }} />,
      { wrapper: LanguageProvider });

    expect(underlined()).toEqual(['Taket ska vara rött.']);
  });
});

describe('SourceViewer with a flagged claim', () => {
  const CLAIM_VIEW = { name: 'Claim that could not be confirmed' };
  const LACKS_BACKING = 'Not backed by the sources';
  const sources: Citation = {
    n: 0,
    label: 'Claim that could not be confirmed',
    chunks: [{ chunk_id: 'c1', source: 'Bygglovstaxa', chunk_index: 0, content: 'Avgiften är 12 000 kr.' }],
  };
  const view = () => within(screen.getByRole('region', CLAIM_VIEW));

  it('shows the claim and that its sources do not say it', () => {
    /** A claim none of whose sentences is named as lacking backing is shown whole, with the plain reason. */
    render(<SourceViewer citation={sources} onClose={vi.fn()}
      claim={{ text: 'The fee is 12 000 kr', verdict: 'unsupported', unbacked: [] }} />, { wrapper: LanguageProvider });

    expect(view().getByText('The fee is 12 000 kr')).toBeInTheDocument();
    expect(view().getByText('The cited sources do not say this.')).toBeInTheDocument();
  });

  it('points out the sentence that lacks backing in a partly backed claim', () => {
    /** Only the sentence the sources do not back is pointed out, and the reason says the rest is backed. */
    render(<SourceViewer citation={sources} onClose={vi.fn()}
      claim={{ text: 'The fee is 12 000 kr. It is paid in advance.', verdict: 'unsupported',
               unbacked: ['It is paid in advance.'] }} />, { wrapper: LanguageProvider });

    expect(view().getAllByTitle(LACKS_BACKING).map((element) => element.textContent)).toEqual(['It is paid in advance.']);
    expect(view().getByText('The cited sources back part of this claim, but not the marked text.')).toBeInTheDocument();
  });

  it('says that a claim has no source', () => {
    /** An uncited claim is shown with the reason that no source is cited. */
    render(<SourceViewer citation={{ ...sources, chunks: [] }} onClose={vi.fn()}
      claim={{ text: 'The fee is 12 000 kr', verdict: 'uncited', unbacked: [] }} />, { wrapper: LanguageProvider });

    expect(view().getByText('No source is cited for this claim.')).toBeInTheDocument();
  });

  it('keeps the cited source texts under the claim', () => {
    /** The chunks the claim cites are listed as for a citation. */
    render(<SourceViewer citation={sources} onClose={vi.fn()}
      claim={{ text: 'The fee is 12 000 kr', verdict: 'unsupported', unbacked: [] }} />, { wrapper: LanguageProvider });

    expect(screen.getAllByText('Avgiften är 12 000 kr.').length).toBeGreaterThan(0);
  });

  it('shows no claim view for a citation alone', () => {
    /** A panel opened from a citation number has no claim view. */
    render(<SourceViewer citation={{ ...sources, n: 1 }} onClose={vi.fn()} />, { wrapper: LanguageProvider });

    expect(screen.queryByRole('region', CLAIM_VIEW)).not.toBeInTheDocument();
  });
});
