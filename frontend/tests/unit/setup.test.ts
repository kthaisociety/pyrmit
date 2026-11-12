// Unit tests for tests/setup.ts and tests/mocks/: the environment every frontend test runs in.
import { render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { expect, it } from 'vitest';

it('renders components in a simulated browser and finds them by role', () => {
  render(createElement('button', null, 'Send'));

  expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
});

it('answers requests from the shared fake backend', async () => {
  const response = await fetch('/api/sessions');

  expect(await response.json()).toHaveLength(2);
});

it.fails('fails a test that sends a request the fake backend does not handle', async () => {
  await fetch('/api/no-such-endpoint').catch(() => undefined);
});
