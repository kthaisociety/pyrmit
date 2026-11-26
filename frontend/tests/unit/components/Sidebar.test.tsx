// Component tests for components/Sidebar.tsx.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import Sidebar from '@/components/Sidebar';
import { LANGUAGE_STORAGE_KEY, LanguageProvider } from '@/lib/i18n';

import { server } from '../../mocks/server';

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const props = {
    currentSessionId: null,
    onSelectSession: vi.fn(),
    onNewChat: vi.fn(),
    refreshTrigger: 0,
    user: { id: 'u1', name: 'anna', email: 'anna@example.com', role: 'developer' as const },
    onOpenSettings: vi.fn(),
    onOpenDatabase: vi.fn(),
    onOpenBenchmark: vi.fn(),
    onOpenPipeline: vi.fn(),
    ...overrides,
  };
  render(<Sidebar {...props} />, { wrapper: LanguageProvider });
  return props;
}

describe('Sidebar', () => {
  it('closes from its menu button', async () => {
    /** The menu button at the top hides the sidebar. */
    const onClose = vi.fn();
    renderSidebar({ onClose });

    await userEvent.click(screen.getByRole('button', { name: 'Close sidebar' }));

    expect(onClose).toHaveBeenCalled();
  });

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

  it('opens the Database view from the sidebar', async () => {
    const props = renderSidebar();

    await userEvent.click(screen.getByRole('button', { name: /Database/ }));

    expect(props.onOpenDatabase).toHaveBeenCalled();
    await screen.findByText('Bygglov Storgatan 3');
  });

  it('opens the Benchmark view from the sidebar', async () => {
    const props = renderSidebar();

    await userEvent.click(screen.getByRole('button', { name: /Benchmark/ }));

    expect(props.onOpenBenchmark).toHaveBeenCalled();
    await screen.findByText('Bygglov Storgatan 3');
  });

  it.each(['owner', 'developer'] as const)('shows the work views to a %s', (role) => {
    renderSidebar({ user: { id: 'u1', name: 'anna', email: 'anna@example.com', role } });

    for (const name of [/Benchmark/, /Pipeline/, /Database/]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  });

  it('hides Benchmark, Pipeline and Database from a plain user', () => {
    /** Issue #112: users chat; the backend refuses them those routes too. */
    renderSidebar({ user: { id: 'u1', name: 'anna', email: 'anna@example.com', role: 'user' } });

    for (const name of [/Benchmark/, /Pipeline/, /Database/]) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: /anna/ })).toBeInTheDocument();
  });

  it('shows its texts in Swedish when Swedish is the chosen language', async () => {
    /** With Swedish chosen (in settings, remembered per browser), the sidebar's texts are Swedish. */
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'sv');
    server.use(http.get('*/api/sessions', () => HttpResponse.json([])));
    renderSidebar();

    expect(await screen.findByRole('button', { name: 'Ny chatt' })).toBeInTheDocument();
  });

  it('shows the user name on a button', async () => {
    /** The bottom of the sidebar has one button named by the user's name. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(screen.getByRole('button', { name: /anna/ })).toBeInTheDocument();
  });

  it('shows the user initial inside the profile button', async () => {
    /** The initial sits on the same button as the name. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(within(screen.getByRole('button', { name: /anna/ })).getByText('A')).toBeInTheDocument();
  });

  it('says on hover that the profile button opens settings', async () => {
    /** The profile button's tooltip reads Settings. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(screen.getByRole('button', { name: /anna/ })).toHaveAttribute('title', 'Settings');
  });

  it('opens settings when the profile button is clicked', async () => {
    /** Clicking the profile button opens the settings view. */
    const props = renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    await userEvent.click(screen.getByRole('button', { name: /anna/ }));

    expect(props.onOpenSettings).toHaveBeenCalled();
  });

  it('has no separate settings button', async () => {
    /** The old Settings button is gone from the sidebar. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(screen.queryByRole('button', { name: /Settings/ })).not.toBeInTheDocument();
  });

  it('has no language switch', async () => {
    /** The language is chosen in settings, not in the sidebar. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(screen.queryByRole('button', { name: 'Svenska' })).not.toBeInTheDocument();
  });

  it('does not show the email', async () => {
    /** The sidebar shows the name only, not the email. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    expect(screen.queryByText('anna@example.com')).not.toBeInTheDocument();
  });

  it('keeps the staff views above the profile button', async () => {
    /** Staff see Database placed before the profile button. */
    renderSidebar();
    await screen.findByText('Bygglov Storgatan 3');

    const database = screen.getByRole('button', { name: /Database/ });
    const profile = screen.getByRole('button', { name: /anna/ });
    expect(database.compareDocumentPosition(profile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows a fallback initial for a user without a name', async () => {
    /** A user with an empty name gets "U" on the profile button. */
    renderSidebar({ user: { id: 'u1', name: '', email: 'anna@example.com', role: 'developer' } });
    await screen.findByText('Bygglov Storgatan 3');

    expect(within(screen.getByTitle('Settings')).getByText('U')).toBeInTheDocument();
  });
});
