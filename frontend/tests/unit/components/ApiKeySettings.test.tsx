// Component tests for components/ApiKeySettings.tsx: the user's own OpenRouter key (issue #108).
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import ApiKeySettings from '@/components/ApiKeySettings';
import { LanguageProvider } from '@/lib/i18n';

import { server } from '../../mocks/server';

const KEY = 'sk-or-v1-' + 'ab12'.repeat(16);

function renderSection() {
  render(<ApiKeySettings />, { wrapper: LanguageProvider });
}

describe('ApiKeySettings', () => {
  it('says the shared key pays when the user has no key', async () => {
    renderSection();

    expect(await screen.findByText('Using the shared key')).toBeInTheDocument();
    expect(screen.getByLabelText('Your OpenRouter API key')).toHaveAttribute('type', 'password');
  });

  it('shows a set key by its last 4 characters only', async () => {
    server.use(http.get('*/api/auth/api-key', () => HttpResponse.json({ enabled: true, has_key: true, last4: 'ab12' })));
    renderSection();

    expect(await screen.findByText('Key set (…ab12)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Your OpenRouter API key')).not.toBeInTheDocument();
  });

  it('says the feature is off when the server has no encryption key', async () => {
    server.use(http.get('*/api/auth/api-key', () => HttpResponse.json({ enabled: false, has_key: false, last4: null })));
    renderSection();

    expect(await screen.findByText(/Own API keys are turned off on this server/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save key' })).not.toBeInTheDocument();
  });

  it('saves a pasted key and clears it from the page', async () => {
    let sent: unknown = null;
    server.use(
      http.put('*/api/auth/api-key', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ enabled: true, has_key: true, last4: 'ab12' });
      }),
    );
    renderSection();

    const input = await screen.findByLabelText('Your OpenRouter API key');
    await userEvent.type(input, `  ${KEY} `);
    await userEvent.click(screen.getByRole('button', { name: 'Save key' }));

    expect(await screen.findByText('Key set (…ab12)')).toBeInTheDocument();
    expect(sent).toEqual({ api_key: KEY });
    expect(document.body.innerHTML).not.toContain(KEY);
  });

  it('replaces a set key', async () => {
    server.use(
      http.get('*/api/auth/api-key', () => HttpResponse.json({ enabled: true, has_key: true, last4: 'ab12' })),
      http.put('*/api/auth/api-key', () => HttpResponse.json({ enabled: true, has_key: true, last4: 'cd34' })),
    );
    renderSection();

    await userEvent.click(await screen.findByRole('button', { name: 'Replace' }));
    await userEvent.type(screen.getByLabelText('Your OpenRouter API key'), 'sk-or-v1-' + 'cd34'.repeat(16));
    await userEvent.click(screen.getByRole('button', { name: 'Save key' }));

    expect(await screen.findByText('Key set (…cd34)')).toBeInTheDocument();
  });

  it('removes a set key and goes back to the shared key', async () => {
    let removed = false;
    server.use(
      http.get('*/api/auth/api-key', () => HttpResponse.json({ enabled: true, has_key: true, last4: 'ab12' })),
      http.delete('*/api/auth/api-key', () => {
        removed = true;
        return HttpResponse.json({ enabled: true, has_key: false, last4: null });
      }),
    );
    renderSection();

    await userEvent.click(await screen.findByRole('button', { name: 'Remove' }));

    expect(await screen.findByText('Using the shared key')).toBeInTheDocument();
    expect(removed).toBe(true);
  });

  it("shows the backend's reason when a key is refused, and clears the field", async () => {
    server.use(
      http.put('*/api/auth/api-key', () =>
        HttpResponse.json({ detail: 'That is not an OpenRouter API key: it starts with sk-or-' }, { status: 400 }),
      ),
    );
    renderSection();

    const input = await screen.findByLabelText('Your OpenRouter API key');
    await userEvent.type(input, 'not-a-key');
    await userEvent.click(screen.getByRole('button', { name: 'Save key' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('That is not an OpenRouter API key');
    await waitFor(() => expect(input).toHaveValue(''));
    expect(screen.getByText('Using the shared key')).toBeInTheDocument();
  });

  it('says so when the settings cannot be read', async () => {
    server.use(http.get('*/api/auth/api-key', () => new HttpResponse(null, { status: 500 })));
    renderSection();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read your API key settings');
  });
});
