// Component tests for components/DatabaseBrowser.tsx.
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DatabaseBrowser from '@/components/DatabaseBrowser';
import type { Role } from '@/lib/roles';

import { server } from '../../mocks/server';

const emptyTable = { total: 0, with_embedding: 0, sources: [] };
const corpusStatus = {
  active: { built: '2026-11-14T19:45:32+00:00', model: 'st-bge-m3', dim: 1024, chunks: 4500, kommuner: 2, uploaded: null },
  previous: null, job: null, uploads: [], history: [], serving: true, part_bytes: 4,
  upload_free_bytes: 25e9, database_bytes: 1e9, disk_limit_bytes: 40e9,
};

beforeEach(() => {
  // The view loads the agent corpus's overview and the first tab's chunks
  server.use(
    http.get('*/api/db/overview', () => HttpResponse.json({ law: emptyTable, document: emptyTable })),
    http.get('*/api/db/chunks', () => HttpResponse.json({ total: 0, offset: 0, limit: 20, items: [] })),
    http.get('*/api/corpus', () => HttpResponse.json(corpusStatus)),
  );
});

describe('DatabaseBrowser', () => {
  it('shows only the agent corpus, named as the backend reports it', async () => {
    /** Issue #114: no "pgvector tables" store button and no Neon any more; the corpus in Postgres only. */
    server.use(
      http.get('*/api/db/sources', () =>
        HttpResponse.json({
          neon: { name: 'pgvector tables', detail: 'law_chunks / document_chunks in db/pyrmit' },
          local: { name: 'Agent corpus · Postgres', detail: 'corpus database db/pyrmit: 4,500 chunks' },
        }),
      ),
    );
    render(<DatabaseBrowser onBack={vi.fn()} />);

    expect(await screen.findByText('Agent corpus · Postgres')).toBeInTheDocument();
    expect(screen.getByText(/corpus database db\/pyrmit: 4,500 chunks/)).toBeInTheDocument();
    expect(screen.queryByText(/pgvector tables/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Neon/)).not.toBeInTheDocument();
  });

  it('keeps a generic label when the backend cannot say', async () => {
    /** An older backend without /api/db/sources still gets a usable view. */
    server.use(http.get('*/api/db/sources', () => new HttpResponse(null, { status: 404 })));
    render(<DatabaseBrowser onBack={vi.fn()} />);

    expect(await screen.findByText('Agent corpus')).toBeInTheDocument();
  });

  it.each<[Role | undefined, boolean, boolean]>([
    ['owner', true, true],
    ['developer', true, false],
    ['user', false, false],
    [undefined, false, false],
  ])('a %s sees the corpus panel: %s, its buttons: %s', async (role, panel, buttons) => {
    server.use(http.get('*/api/db/sources', () => new HttpResponse(null, { status: 404 })));
    render(<DatabaseBrowser onBack={vi.fn()} role={role} />);

    await screen.findByText('Agent corpus');
    if (panel) {
      expect(await screen.findByRole('region', { name: 'Corpus' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Upload and replace/ }) !== null).toBe(buttons);
    } else {
      expect(screen.queryByRole('region', { name: 'Corpus' })).not.toBeInTheDocument();
    }
  });
});
