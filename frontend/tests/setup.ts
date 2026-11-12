import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import { server } from './mocks/server';

// A request with no handler never reaches a real server (PCR-0008). MSW only rejects the
// fetch, and a component can catch that, so we also record each one and fail the test below.
const unhandled: string[] = [];

beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' });
  server.events.on('request:unhandled', ({ request }) => {
    unhandled.push(`${request.method} ${request.url}`);
  });
});
beforeEach(() => {
  unhandled.length = 0;
});
afterEach(() => {
  server.resetHandlers();
  cleanup();
  window.localStorage.clear();
  if (unhandled.length > 0) {
    throw new Error(`Requests with no MSW handler:\n${unhandled.join('\n')}`);
  }
});
afterAll(() => server.close());
