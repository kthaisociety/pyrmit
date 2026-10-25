// Acceptance tests for #34: the frontend test suite on the v1 line. Temporary, folded into tests/unit/ by
// refactor-issue (PCR-0007).
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import Sidebar from '@/components/Sidebar';

function renderSidebar() {
  const props = {
    currentSessionId: null,
    onSelectSession: vi.fn(),
    onNewChat: vi.fn(),
    refreshTrigger: 0,
    user: { id: 'u1', name: 'anna', email: 'anna@example.com' },
    onOpenSettings: vi.fn(),
    onOpenDatabase: vi.fn(),
    onOpenBenchmark: vi.fn(),
  };
  render(createElement(Sidebar, props));
  return props;
}

describe('frontend test suite', () => {
  it('renders components in a simulated browser and finds them by role', () => {
    /** Component tests run in jsdom with React Testing Library. */
    render(createElement('button', null, 'Send'));

    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
  });

  it('answers requests from the shared fake backend', async () => {
    /** The default MSW handlers stand in for the backend in every test. */
    const response = await fetch('/api/sessions');

    expect(await response.json()).toHaveLength(2);
  });

  it.fails('fails a test that sends a request the fake backend does not handle', async () => {
    /** An unhandled request never reaches a real server and fails the test that sent it (PCR-0008). */
    await fetch('/api/no-such-endpoint').catch(() => undefined);
  });
});

describe('v1 sidebar under test', () => {
  it('opens the Database view from the sidebar', async () => {
    /** The v1 sidebar's Database button works in the suite. */
    const props = renderSidebar();

    await userEvent.click(screen.getByRole('button', { name: /Database/ }));

    expect(props.onOpenDatabase).toHaveBeenCalled();
    await screen.findByText('Bygglov Storgatan 3');
  });

  it('opens the Benchmark view from the sidebar', async () => {
    /** The v1 sidebar's Benchmark button works in the suite. */
    const props = renderSidebar();

    await userEvent.click(screen.getByRole('button', { name: /Benchmark/ }));

    expect(props.onOpenBenchmark).toHaveBeenCalled();
    await screen.findByText('Bygglov Storgatan 3');
  });
});
