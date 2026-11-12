// Unit tests for app/(protected)/auth/page.tsx: the sign-in page.
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AuthPage from '@/app/(protected)/auth/page';
import { LanguageProvider } from '@/lib/i18n';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

describe('sign-in page', () => {
  it('carries the language switch', () => {
    /** The sign-in page has the Svenska / English switch. */
    render(<AuthPage />, { wrapper: LanguageProvider });

    expect(screen.getByRole('button', { name: 'Svenska' })).toBeInTheDocument();
  });
});
