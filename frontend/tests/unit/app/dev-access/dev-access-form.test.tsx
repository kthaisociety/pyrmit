// Unit tests for app/dev-access/dev-access-form.tsx: the access gate form.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import DevAccessForm from '@/app/dev-access/dev-access-form';
import { LanguageProvider } from '@/lib/i18n';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

describe('access gate form', () => {
  it('carries the language switch', () => {
    /** The access gate form has the Svenska / English switch. */
    render(<DevAccessForm nextPath="/" />, { wrapper: LanguageProvider });

    expect(screen.getByRole('button', { name: 'Svenska' })).toBeInTheDocument();
  });

  it('shows its texts in Swedish once Svenska is chosen', async () => {
    /** Choosing Svenska turns the gate's heading Swedish. */
    render(<DevAccessForm nextPath="/" />, { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(screen.getByText('Ange det gemensamma lösenordet')).toBeInTheDocument();
  });
});
