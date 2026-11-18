// Component tests for components/PipelineBrowser.tsx.
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import PipelineBrowser from '@/components/PipelineBrowser';

import { server } from '../../mocks/server';

describe('PipelineBrowser', () => {
  it('says the numbers are the national corpus when this install serves the Neon extract', async () => {
    /** The other developers have no corpus: the backend sends the national page, measured where it is built. */
    server.use(
      http.get('*/api/pipeline', () =>
        HttpResponse.json({ corpus: 'data', steps: [], snapshot: { built: '2026-11-01' } }),
      ),
    );
    render(<PipelineBrowser onBack={vi.fn()} />);

    expect(await screen.findByText('national corpus, measured on 2026-11-01')).toBeInTheDocument();
    expect(screen.getByText(/searches an extract of it hosted on Neon/)).toBeInTheDocument();
  });

  it('shows the corpus it measures live otherwise', async () => {
    server.use(http.get('*/api/pipeline', () => HttpResponse.json({ corpus: 'data', steps: [] })));
    render(<PipelineBrowser onBack={vi.fn()} />);

    expect(await screen.findByText('corpus: data')).toBeInTheDocument();
    expect(screen.queryByText(/hosted on Neon/)).not.toBeInTheDocument();
  });

  it('shows the rebuild costs after the steps, unnumbered and outside the strip', async () => {
    /** The costs cover running every step: a 7th numbered step would read as a step after the tools. */
    const card = (id: string, title: string, step?: number) => ({
      id, ...(step ? { step } : {}), title, what: '', measure: '', status: { level: 'info', label: 'ok' },
      flow: { value: 1, caption: '' }, tiles: [], sections: [],
    });
    server.use(
      http.get('*/api/pipeline', () =>
        HttpResponse.json({ corpus: 'data', steps: [card('crawl', 'Crawl the sites', 1)], costs: card('costs', 'Whole pipeline: time and cost') }),
      ),
    );
    render(<PipelineBrowser onBack={vi.fn()} />);

    expect(await screen.findByText('Running the whole pipeline')).toBeInTheDocument();
    expect(screen.getByText('Whole pipeline: time and cost')).toBeInTheDocument();
    expect(screen.getByLabelText('All steps')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });
});
