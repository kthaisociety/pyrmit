// Component tests for components/BenchmarkOverview.tsx: the approaches tested and their success rates (issue #116).
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import BenchmarkOverview, { type BenchmarkSummary, type Cell, pct } from '@/components/BenchmarkOverview';

import { server } from '../../mocks/server';

function cell(success: number, cost: number, seconds: number, extra: Partial<Cell> = {}): Cell {
  return {
    n: 28, success, verdict: success, points: 0.6, evidence: 0.8, grounded: 0.85, unsupported: 1.2, tools: 20,
    seconds, first: seconds - 6, cost, files: ['bench-20261007-215229-agent-medium-explore-medium.json'], ...extra,
  };
}

const SUMMARY: BenchmarkSummary = {
  sets: [
    { key: 'cases14', name: '14 case studies', about: 'Hand-written feasibility questions.', measure: 'verdict' },
    { key: 'caselaw', name: 'Court rulings (MÖD)', about: 'Real appeals.', measure: 'verdict' },
  ],
  measures: [
    { key: 'success', name: 'Success rate', text: 'Share of answers whose verdict is right.' },
    { key: 'cost', name: 'Cost', text: 'Model cost of one answer.' },
  ],
  studies: [
    {
      key: 'rag-vs-agent',
      title: 'Classic RAG or a tool-using agent?',
      about: 'Same model and corpus.',
      reading: 'The agent wins where the deciding rule has to be found.',
      period: ['2026-10-07', '2026-10-17'],
      sets: ['cases14', 'caselaw'],
      configs: [
        {
          key: 'rag-medium', name: 'Classic RAG', settings: 'answer effort medium', about: 'One search.', system: 'rag',
          results: { cases14: cell(1, 0.0017, 16), caselaw: cell(0.6, 0.002, 23) },
          overall: { success: 0.8, points: 0.4, cost: 0.0019 },
        },
        {
          key: 'agent-low-medium', name: 'Tool-using agent', settings: 'exploration low · answer medium',
          about: 'Works in turns.', system: 'agent', results: { caselaw: cell(0.75, 0.0036, 26) },
        },
        {
          key: 'agent-medium-medium', name: 'Tool-using agent', settings: 'exploration medium · answer medium',
          about: 'Works in turns.', system: 'agent',
          results: { cases14: cell(1, 0.0071, 31), caselaw: cell(0.7, 0.0086, 43, { n: 200 }) },
          overall: { success: 0.85, points: 0.62, cost: 0.0078 },
        },
      ],
      best_by_set: { cases14: 'agent-medium-medium', caselaw: 'agent-low-medium' },
      best: 'agent-medium-medium',
      in_use: 'agent-medium-medium',
    },
  ],
};

function serve(body: BenchmarkSummary = SUMMARY) {
  server.use(http.get('*/api/benchmark/summary', () => HttpResponse.json(body)));
}

describe('BenchmarkOverview', () => {
  it('shows each study as solutions by benchmark set with their success rate, cost and time', async () => {
    serve();
    render(<BenchmarkOverview />);

    const study = await screen.findByRole('region', { name: 'Classic RAG or a tool-using agent?' });
    const rows = within(study).getAllByRole('row');
    expect(rows[0]).toHaveTextContent('14 case studies');
    expect(rows[0]).toHaveTextContent('right verdict');
    expect(rows[1]).toHaveTextContent('Classic RAG');
    expect(rows[1]).toHaveTextContent('100 %');
    expect(rows[1]).toHaveTextContent('60 %');
    expect(rows[1]).toHaveTextContent('$0.0020 · 23 s');
    expect(rows[2]).toHaveTextContent('–'); // not run on the 14 cases
    expect(within(study).getByText(/The agent wins where the deciding rule/)).toBeInTheDocument();
    expect(within(study).getByText('2026-10-07 to 2026-10-17')).toBeInTheDocument();
  });

  it('highlights the best configuration and the best result of each set', async () => {
    serve();
    render(<BenchmarkOverview />);

    const study = await screen.findByRole('region', { name: 'Classic RAG or a tool-using agent?' });
    expect(within(study).getByText(/Best overall:/)).toHaveTextContent(
      'Best overall: Tool-using agent (exploration medium · answer medium), 85 % average success rate, $0.0078 per answer.',
    );
    const rows = within(study).getAllByRole('row');
    expect(within(rows[3]).getByText('Best')).toBeInTheDocument();
    expect(within(rows[3]).getByText('In use')).toBeInTheDocument();
    expect(within(rows[1]).queryByText('Best')).not.toBeInTheDocument();
    const best = study.querySelectorAll('[data-best]');
    // Both 100 % on the 14 cases: a tie is green on both rows
    expect(Array.from(best).map((td) => td.textContent)).toEqual([
      '100 %$0.0017 · 16 s', '75 %$0.0036 · 26 s', '100 %$0.0071 · 31 s']);
  });

  it('shows a solution’s full measures on demand', async () => {
    serve();
    render(<BenchmarkOverview />);

    const toggle = await screen.findByRole('button', { name: /exploration medium · answer medium: details/ });
    expect(screen.queryByText('Answers judged')).not.toBeInTheDocument();
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const details = screen.getByText('Answers judged').closest('table')!;
    expect(details).toHaveTextContent('200'); // answers on the court rulings
    expect(details).toHaveTextContent('Grounding85 %85 %');
    expect(details).toHaveTextContent('43 s (37 s)');
    expect(screen.getByText(/From bench-20261007-215229/)).toBeInTheDocument();
  });

  it('explains the sets and how answers are scored', async () => {
    serve();
    render(<BenchmarkOverview />);

    await userEvent.click(await screen.findByText('What each benchmark set tests (2)'));
    expect(screen.getByText('Hand-written feasibility questions.')).toBeVisible();
    expect(screen.getByText('How answers are scored')).toBeInTheDocument();
    expect(screen.getByText('Share of answers whose verdict is right.')).toBeInTheDocument();
  });

  it('leads to the case-by-case view', async () => {
    serve();
    const onShowCases = vi.fn();
    render(<BenchmarkOverview onShowCases={onShowCases} />);

    await userEvent.click(await screen.findByRole('button', { name: /See every case/ }));
    expect(onShowCases).toHaveBeenCalled();
  });

  it('says so when there are no results or they cannot be loaded', async () => {
    serve({ ...SUMMARY, studies: [] });
    const { unmount } = render(<BenchmarkOverview />);
    expect(await screen.findByText('No benchmark results on this server.')).toBeInTheDocument();
    unmount();

    server.use(http.get('*/api/benchmark/summary', () => HttpResponse.json({ detail: 'x' }, { status: 403 })));
    render(<BenchmarkOverview />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the benchmark results');
  });

  it('formats rates as rounded percentages', () => {
    expect(pct(0.625)).toBe('63 %');
    expect(pct(null)).toBe('–');
  });
});
