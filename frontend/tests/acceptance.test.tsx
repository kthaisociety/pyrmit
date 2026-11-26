// Acceptance tests for issue #133: settings open from a profile button, and the language is chosen in settings.
// Lives only on this branch; unit-test-ticket folds it into Sidebar.test.tsx and Settings.test.tsx.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import Settings from '@/components/Settings';
import Sidebar from '@/components/Sidebar';
import { LanguageProvider } from '@/lib/i18n';
import type { CurrentUser } from '@/lib/roles';

const anna: CurrentUser = { id: 'u1', name: 'anna', email: 'anna@example.com', role: 'developer' };

async function renderSidebar(user: CurrentUser = anna) {
  const onOpenSettings = vi.fn();
  render(
    <Sidebar
      currentSessionId={null}
      onSelectSession={vi.fn()}
      onNewChat={vi.fn()}
      refreshTrigger={0}
      user={user}
      onOpenSettings={onOpenSettings}
      onOpenDatabase={vi.fn()}
      onOpenBenchmark={vi.fn()}
      onOpenPipeline={vi.fn()}
    />,
    { wrapper: LanguageProvider },
  );
  await screen.findByText('Bygglov Storgatan 3');
  return { onOpenSettings };
}

function renderSettings() {
  render(
    <Settings
      user={anna}
      onBack={vi.fn()}
      onLogout={vi.fn()}
      logoutLoading={false}
      logoutError=""
      onUserUpdated={vi.fn()}
      onAllChatsCleared={vi.fn()}
    />,
    { wrapper: LanguageProvider },
  );
}

describe('Sidebar profile button (#133)', () => {
  it('shows the user name on a button', async () => {
    /** The bottom of the sidebar has one button named by the user's name. */
    await renderSidebar();

    expect(screen.getByRole('button', { name: /anna/ })).toBeInTheDocument();
  });

  it('shows the user initial inside the profile button', async () => {
    /** The initial sits on the same button as the name. */
    await renderSidebar();

    expect(within(screen.getByRole('button', { name: /anna/ })).getByText('A')).toBeInTheDocument();
  });

  it('says on hover that the profile button opens settings', async () => {
    /** The profile button's tooltip reads Settings. */
    await renderSidebar();

    expect(screen.getByRole('button', { name: /anna/ })).toHaveAttribute('title', 'Settings');
  });

  it('opens settings when the profile button is clicked', async () => {
    /** Clicking the profile button opens the settings view. */
    const { onOpenSettings } = await renderSidebar();

    await userEvent.click(screen.getByRole('button', { name: /anna/ }));

    expect(onOpenSettings).toHaveBeenCalled();
  });

  it('has no separate settings button', async () => {
    /** The old Settings button is gone from the sidebar. */
    await renderSidebar();

    expect(screen.queryByRole('button', { name: /Settings/ })).not.toBeInTheDocument();
  });

  it('has no language switch', async () => {
    /** The Svenska / English switch is no longer in the sidebar. */
    await renderSidebar();

    expect(screen.queryByRole('button', { name: 'Svenska' })).not.toBeInTheDocument();
  });

  it('does not show the email', async () => {
    /** The sidebar shows the name only, not the email. */
    await renderSidebar();

    expect(screen.queryByText('anna@example.com')).not.toBeInTheDocument();
  });

  it('keeps the staff views above the profile button', async () => {
    /** Staff still see Database, placed before the profile button. */
    await renderSidebar();

    const database = screen.getByRole('button', { name: /Database/ });
    const profile = screen.getByRole('button', { name: /anna/ });
    expect(database.compareDocumentPosition(profile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows a fallback initial for a user without a name', async () => {
    /** A user with an empty name gets "U" on the profile button. */
    await renderSidebar({ ...anna, name: '' });

    expect(within(screen.getByTitle('Settings')).getByText('U')).toBeInTheDocument();
  });
});

describe('Settings language section (#133)', () => {
  it('has a language section', () => {
    /** The settings view carries a Language heading. */
    renderSettings();

    expect(screen.getByRole('heading', { name: 'Language' })).toBeInTheDocument();
  });

  it('places the language section first', () => {
    /** Language is the first section heading of the settings view. */
    renderSettings();

    expect(screen.getAllByRole('heading', { level: 2 })[0]).toHaveTextContent('Language');
  });

  it('switches the page to Swedish from settings', async () => {
    /** Choosing Svenska in settings turns the settings texts Swedish at once. */
    renderSettings();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(await screen.findByRole('heading', { name: 'Inställningar' })).toBeInTheDocument();
  });

  it('names the language section in Swedish once Svenska is chosen', async () => {
    /** The section's own heading reads Språk on the Swedish page. */
    renderSettings();

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(await screen.findByRole('heading', { name: 'Språk' })).toBeInTheDocument();
  });
});
