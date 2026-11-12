// Unit tests for components/LanguageSwitch.tsx: the SV / EN switch of the page language.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import LanguageSwitch from '@/components/LanguageSwitch';
import { LanguageProvider } from '@/lib/i18n';

afterEach(() => {
  document.documentElement.lang = '';
});

describe('LanguageSwitch', () => {
  it('switches the page to Swedish', async () => {
    /** Choosing Svenska sets the page language to Swedish. */
    render(<LanguageSwitch />, { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(document.documentElement.lang).toBe('sv');
  });

  it('marks the chosen language as pressed', async () => {
    /** After choosing Svenska its button is pressed. */
    render(<LanguageSwitch />, { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(screen.getByRole('button', { name: 'Svenska' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('marks the other language as not pressed', async () => {
    /** After choosing Svenska the English button is not pressed. */
    render(<LanguageSwitch />, { wrapper: LanguageProvider });

    await userEvent.click(screen.getByRole('button', { name: 'Svenska' }));

    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'false');
  });
});
