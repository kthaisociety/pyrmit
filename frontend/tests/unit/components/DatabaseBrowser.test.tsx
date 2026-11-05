// Component tests for components/DatabaseBrowser.tsx.
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DatabaseBrowser from '@/components/DatabaseBrowser';

import { server } from '../../mocks/server';

const emptyTable = { total: 0, with_embedding: 0, sources: [] };

beforeEach(() => {
  // The view loads the selected store's overview and the first tab's chunks
  server.use(
    http.get('*/api/db/overview', () => HttpResponse.json({ law: emptyTable, document: emptyTable })),
    http.get('*/api/db/chunks', () => HttpResponse.json({ total: 0, offset: 0, limit: 20, items: [] })),
  );
});

describe('DatabaseBrowser', () => {
  it('names the real source of each store, as the backend reports it', async () => {
    /** On the hosted demo the agent's corpus comes from Neon, not from local files: the buttons say so. */
    server.use(
      http.get('*/api/db/sources', () =>
        HttpResponse.json({
          neon: { name: 'pgvector tables', detail: 'law_chunks / document_chunks in ep-prod/neondb' },
          local: { name: 'Agent corpus · Neon', detail: 'corpus database ep-demo/neondb: 115,127 chunks' },
        }),
      ),
    );
    render(<DatabaseBrowser onBack={vi.fn()} />);

    expect(await screen.findByRole('button', { name: 'Agent corpus · Neon' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'pgvector tables' })).toBeInTheDocument();
    expect(screen.getByText(/corpus database ep-demo\/neondb/)).toBeInTheDocument();
  });

  it('keeps generic labels when the backend cannot say', async () => {
    /** An older backend without /api/db/sources still gets a usable view. */
    server.use(http.get('*/api/db/sources', () => new HttpResponse(null, { status: 404 })));
    render(<DatabaseBrowser onBack={vi.fn()} />);

    expect(await screen.findByRole('button', { name: 'Agent corpus' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'pgvector tables' })).toBeInTheDocument();
  });
});
