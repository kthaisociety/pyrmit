// Run with Node 22.18+: node --test lib/auth.test.mjs
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { authFetch } from './auth.ts';

const originalFetch = globalThis.fetch;
let storedToken;
let redirects;

beforeEach(() => {
  storedToken = 'test-jwt';
  redirects = [];
  globalThis.window = {
    localStorage: {
      getItem: () => storedToken,
      removeItem: () => { storedToken = null; },
    },
    location: {
      href: 'http://localhost/', pathname: '/', search: '',
      assign: (url) => redirects.push(url),
    },
  };
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});

test('protected 401 sends bearer token, clears it and redirects', async () => {
  globalThis.fetch = async (_input, init) => {
    assert.equal(init.headers.get('Authorization'), 'Bearer test-jwt');
    return Response.json({ detail: 'Could not validate credentials' }, { status: 401 });
  };
  await authFetch('/api/auth/signout', { method: 'POST' });
  assert.equal(storedToken, null);
  assert.deepEqual(redirects, ['/auth']);
});

test('login errors preserve token and stay on page', async () => {
  globalThis.fetch = async () => Response.json({}, { status: 401 });
  for (const path of ['token', 'signin', 'signup']) await authFetch(`/api/auth/${path}`);
  assert.equal(storedToken, 'test-jwt');
  assert.deepEqual(redirects, []);
});

test('access gate redirects separately without clearing JWT', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'Access password required' }, { status: 401 });
  await authFetch('/api/auth/signout');
  assert.equal(storedToken, 'test-jwt');
  assert.deepEqual(redirects, ['/dev-access']);
});

test('403, server and network errors preserve token', async () => {
  for (const status of [403, 500, 503]) {
    globalThis.fetch = async () => Response.json({}, { status });
    await authFetch('/api/auth/me');
  }
  globalThis.fetch = async () => { throw new TypeError('Network error'); };
  await assert.rejects(authFetch('/api/auth/signout'));
  assert.equal(storedToken, 'test-jwt');
  assert.deepEqual(redirects, []);
});
