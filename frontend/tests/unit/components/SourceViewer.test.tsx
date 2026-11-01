// Component tests for components/SourceViewer.tsx.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SourceViewer, { Citation } from '@/components/SourceViewer';

import { server } from '../../mocks/server';

const citation: Citation = {
  n: 1,
  label: 'Vallentuna – Detaljplan Kårsta',
  chunks: [{ chunk_id: 'c1', source: 'Detaljplan Kårsta', chunk_index: 3, content: 'Nockhöjd 8 m', doc_id: 'pdf:0115:aa' }],
};
const located = { type: 'pdf', page: 3, found: true, highlighted: true, pdf_url: '/api/docs/pdf/c1', view: null };

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:pdf', revokeObjectURL: () => {} }));
  server.use(http.get('*/api/docs/pdf/c1', () => new HttpResponse(new Blob(['%PDF-1.7']), { status: 200 })));
});

describe('SourceViewer', () => {
  it('says the PDF is being downloaded from the kommun site when this install does not have it', async () => {
    /** Corpus on Neon: the first opening fetches the PDF from the kommun's website, which takes seconds. */
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
    render(<SourceViewer citation={citation} onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /Open the PDF at this passage/ }));

    expect(await screen.findByRole('status')).toHaveTextContent('Downloading the PDF from www.vallentuna.se');
    finishDownload();
    expect(await screen.findByText('Page 3, cited passage highlighted.')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('opens a PDF already on this machine without a download message', async () => {
    /** The crawl folder or the cache has it: one locate call, straight to the page. */
    const asked: string[] = [];
    server.use(
      http.get('*/api/docs/locate', ({ request }) => {
        asked.push(new URL(request.url).search);
        return HttpResponse.json(located);
      }),
    );
    render(<SourceViewer citation={citation} onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /Open the PDF at this passage/ }));

    expect(await screen.findByText('Page 3, cited passage highlighted.')).toBeInTheDocument();
    expect(screen.queryByText(/Downloading/)).not.toBeInTheDocument();
    expect(asked).toEqual(['?chunk_id=c1&download=false']);
  });
});
