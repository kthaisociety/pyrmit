// Unit tests for components/BenchmarkBrowser.tsx.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BenchmarkBrowser from '@/components/BenchmarkBrowser';

import { server } from '../../mocks/server';

beforeEach(() => {
  server.use(
    http.get('*/api/benchmark/sets', () =>
      HttpResponse.json([{ set: 'cases', title: 'Case studies', description: 'Hand-written cases', cases: 14 }]),
    ),
    http.get('*/api/benchmark/cases', () =>
      HttpResponse.json({ items: [{ id: 'kumla-200m2', question: 'Can I build 200 m²?', verdicts: ['not_feasible'], has_image: false }], total: 1 }),
    ),
    http.get('*/api/benchmark/summary', () => HttpResponse.json({ sets: [], measures: [], studies: [] })),
  );
});

describe('BenchmarkBrowser', () => {
  it('opens on the approaches tested, the cases one click away', async () => {
    /** Issue #116: a reader without the project's context sees the solutions and their success rates first. */
    render(<BenchmarkBrowser onBack={vi.fn()} />);

    expect(screen.getByRole('tab', { name: 'Approaches tested' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('No benchmark results on this server.')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Filter cases/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Case by case' }));

    expect(screen.getByPlaceholderText(/Filter cases/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /Case studies/ })).toBeInTheDocument();
  });
});
