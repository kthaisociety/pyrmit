// Component tests for components/UserRoleSettings.tsx: owners change users' roles (issue #112).
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import UserRoleSettings, { type UserRow } from '@/components/UserRoleSettings';
import { LanguageProvider } from '@/lib/i18n';

import { server } from '../../mocks/server';

const ROWS: UserRow[] = [
  { id: 'o', name: 'Olle', email: 'olle@kth.se', role: 'owner', from_owner_emails: false },
  { id: 'd', name: 'Dana', email: 'dana@kth.se', role: 'developer', from_owner_emails: false },
  { id: 'u', name: 'Ulla', email: 'ulla@kth.se', role: 'user', from_owner_emails: false },
];

function renderSection(rows: UserRow[] = ROWS) {
  server.use(http.get('*/api/users', () => HttpResponse.json(rows)));
  render(<UserRoleSettings currentUserId="o" />, { wrapper: LanguageProvider });
}

describe('UserRoleSettings', () => {
  it('lists every user with their role and marks the current one', async () => {
    renderSection();

    expect(await screen.findByLabelText('Role of ulla@kth.se')).toHaveValue('user');
    expect(screen.getByLabelText('Role of dana@kth.se')).toHaveValue('developer');
    expect(screen.getByText('(you)')).toBeInTheDocument();
  });

  it('changes a role through the backend', async () => {
    let sent: unknown = null;
    server.use(
      http.patch('*/api/users/u/role', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ ...ROWS[2], role: 'developer' });
      }),
    );
    renderSection();

    await userEvent.selectOptions(await screen.findByLabelText('Role of ulla@kth.se'), 'developer');

    await waitFor(() => expect(screen.getByLabelText('Role of ulla@kth.se')).toHaveValue('developer'));
    expect(sent).toEqual({ role: 'developer' });
  });

  it('locks the last owner and owners set by OWNER_EMAILS', async () => {
    renderSection();
    expect(await screen.findByLabelText('Role of olle@kth.se')).toBeDisabled();
    expect(screen.getByText(/The last owner/)).toBeInTheDocument();
  });

  it('locks an OWNER_EMAILS owner even when there are other owners', async () => {
    renderSection([
      { ...ROWS[0], from_owner_emails: true },
      { ...ROWS[1], role: 'owner' },
    ]);
    expect(await screen.findByLabelText('Role of olle@kth.se')).toBeDisabled();
    expect(screen.getByLabelText('Role of dana@kth.se')).toBeEnabled();
    expect(screen.getByText(/Owner through OWNER_EMAILS/)).toBeInTheDocument();
  });

  it('shows the backend refusal and keeps the old role', async () => {
    server.use(
      http.patch('*/api/users/d/role', () =>
        HttpResponse.json({ detail: 'This is the last owner: make someone else owner first' }, { status: 409 }),
      ),
    );
    renderSection();

    await userEvent.selectOptions(await screen.findByLabelText('Role of dana@kth.se'), 'user');

    expect(await screen.findByRole('alert')).toHaveTextContent('last owner');
    expect(screen.getByLabelText('Role of dana@kth.se')).toHaveValue('developer');
  });

  it('says so when the users cannot be loaded', async () => {
    server.use(http.get('*/api/users', () => HttpResponse.json({ detail: 'nope' }, { status: 403 })));
    render(<UserRoleSettings currentUserId="o" />, { wrapper: LanguageProvider });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the users');
  });
});
