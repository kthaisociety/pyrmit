// Component tests for components/Sidebar.tsx.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import Sidebar from '@/components/Sidebar';

import { server } from '../../mocks/server';

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const props = {
    currentSessionId: null,
    onSelectSession: vi.fn(),
    onNewChat: vi.fn(),
    refreshTrigger: 0,
    user: { id: 'u1', name: 'anna', email: 'anna@example.com' },
    onOpenSettings: vi.fn(),
    ...overrides,
  };
  render(<Sidebar {...props} />);
  return props;
}

describe('Sidebar', () => {
  it('lists the sessions from the backend, with a fallback title for untitled ones', async () => {
    renderSidebar();

    expect(await screen.findByText('Bygglov Storgatan 3')).toBeInTheDocument();
    expect(screen.getAllByText('New Chat')).toHaveLength(2); // the button and the untitled session
  });

  it('shows an empty state when there are no sessions', async () => {
    server.use(http.get('*/api/sessions', () => HttpResponse.json([])));
    renderSidebar();

    expect(await screen.findByText('No chat history')).toBeInTheDocument();
  });

  it('selects a session when it is clicked', async () => {
    const props = renderSidebar();

    await userEvent.click(await screen.findByText('Bygglov Storgatan 3'));

    expect(props.onSelectSession).toHaveBeenCalledWith('s1');
  });

  it('deletes the current session after confirmation and starts a new chat', async () => {
    let deletedId: string | undefined;
    server.use(
      http.delete('*/api/sessions/:sessionId', ({ params }) => {
        deletedId = params.sessionId as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const props = renderSidebar({ currentSessionId: 's1' });
    await screen.findByText('Bygglov Storgatan 3');

    await userEvent.click(screen.getAllByTitle('Delete')[0]);
    await userEvent.click(screen.getByTitle('Confirm delete'));

    await waitFor(() => expect(screen.queryByText('Bygglov Storgatan 3')).not.toBeInTheDocument());
    expect(deletedId).toBe('s1');
    expect(props.onNewChat).toHaveBeenCalled();
  });

  it('shows the user initial and email', async () => {
    renderSidebar();

    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('anna@example.com')).toBeInTheDocument();
    await screen.findByText('Bygglov Storgatan 3');
  });
});
