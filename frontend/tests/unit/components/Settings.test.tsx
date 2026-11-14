// Unit tests for components/Settings.tsx.
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import Settings from '@/components/Settings';
import { LanguageProvider } from '@/lib/i18n';
import type { Role } from '@/lib/roles';

import { server } from '../../mocks/server';

function renderSettings(role: Role) {
  server.use(
    http.get('*/api/users', () =>
      HttpResponse.json([{ id: 'me', name: 'Me', email: 'me@kth.se', role, from_owner_emails: false }]),
    ),
  );
  render(
    <Settings
      user={{ id: 'me', name: 'Me', email: 'me@kth.se', role }}
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

describe('Settings', () => {
  it('shows the user their role', () => {
    renderSettings('developer');
    expect(screen.getByText('Role: Developer')).toBeInTheDocument();
  });

  it('shows the users and roles section to owners', async () => {
    renderSettings('owner');
    expect(await screen.findByText('Users and roles')).toBeInTheDocument();
    expect(await screen.findByLabelText('Role of me@kth.se')).toBeInTheDocument();
  });

  it.each<Role>(['developer', 'user'])('hides the users and roles section from a %s', (role) => {
    renderSettings(role);
    expect(screen.queryByText('Users and roles')).not.toBeInTheDocument();
  });
});
