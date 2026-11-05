// Unit tests for lib/auth.ts.
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  authFetch,
  clearAccessToken,
  getAuthHeaders,
  getStoredAccessToken,
  storeAccessToken,
} from '@/lib/auth';

import { server } from '../../mocks/server';

describe('access token storage', () => {
  it('returns null when no token is stored', () => {
    expect(getStoredAccessToken()).toBeNull();
  });

  it('returns the token after storing it, and null after clearing it', () => {
    storeAccessToken('abc');
    expect(getStoredAccessToken()).toBe('abc');

    clearAccessToken();
    expect(getStoredAccessToken()).toBeNull();
  });
});

describe('getAuthHeaders', () => {
  it('adds a bearer token when one is stored', () => {
    storeAccessToken('abc');
    expect(getAuthHeaders().get('Authorization')).toBe('Bearer abc');
  });

  it('leaves Authorization unset when no token is stored', () => {
    expect(getAuthHeaders().has('Authorization')).toBe(false);
  });

  it('keeps headers passed in by the caller', () => {
    const headers = getAuthHeaders({ 'Content-Type': 'application/json' });
    expect(headers.get('Content-Type')).toBe('application/json');
  });
});

describe('authFetch', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends the stored token to the backend', async () => {
    storeAccessToken('abc');
    let sentAuthorization: string | null = null;
    server.use(
      http.get('*/api/auth/me', ({ request }) => {
        sentAuthorization = request.headers.get('Authorization');
        return HttpResponse.json({ id: 'u1' });
      }),
    );

    await authFetch('/api/auth/me');

    expect(sentAuthorization).toBe('Bearer abc');
  });

  it('redirects to the access gate when the backend asks for the access password', async () => {
    const assign = vi.fn();
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...window.location,
      pathname: '/chat',
      search: '?x=1',
      assign,
    });
    server.use(
      http.get('*/api/auth/me', () =>
        HttpResponse.json({ detail: 'Access password required' }, { status: 401 }),
      ),
    );

    const response = await authFetch('/api/auth/me');

    expect(response.status).toBe(401);
    expect(assign).toHaveBeenCalledWith('/dev-access?next=%2Fchat%3Fx%3D1');
  });

  it('keeps the JWT when redirecting to the access gate', async () => {
    storeAccessToken('abc');
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign: vi.fn() });
    server.use(
      http.get('*/api/auth/me', () =>
        HttpResponse.json({ detail: 'Access password required' }, { status: 401 }),
      ),
    );

    await authFetch('/api/auth/me');

    expect(getStoredAccessToken()).toBe('abc');
  });
});

describe('authFetch on a revoked or expired login', () => {
  let assign: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    assign = vi.fn();
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, pathname: '/', assign });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const unauthorized = () => HttpResponse.json({ detail: 'Could not validate credentials' }, { status: 401 });

  it('clears the token and opens the sign-in page on a protected 401', async () => {
    storeAccessToken('abc');
    server.use(http.post('*/api/auth/signout', unauthorized));

    await authFetch('/api/auth/signout', { method: 'POST' });

    expect(getStoredAccessToken()).toBeNull();
    expect(assign).toHaveBeenCalledWith('/auth');
  });

  it.each(['token', 'signin', 'signup'])('keeps the token and the page when /api/auth/%s fails', async (path) => {
    storeAccessToken('abc');
    server.use(http.post(`*/api/auth/${path}`, unauthorized));

    await authFetch(`/api/auth/${path}`, { method: 'POST' });

    expect(getStoredAccessToken()).toBe('abc');
    expect(assign).not.toHaveBeenCalled();
  });

  it.each([403, 500, 503])('keeps the token on a %i', async (status) => {
    storeAccessToken('abc');
    server.use(http.get('*/api/auth/me', () => HttpResponse.json({}, { status })));

    await authFetch('/api/auth/me');

    expect(getStoredAccessToken()).toBe('abc');
    expect(assign).not.toHaveBeenCalled();
  });

  it('keeps the token on a network error', async () => {
    storeAccessToken('abc');
    server.use(http.get('*/api/auth/me', () => HttpResponse.error()));

    await expect(authFetch('/api/auth/me')).rejects.toThrow();

    expect(getStoredAccessToken()).toBe('abc');
  });

  // The 401 is held back until another tab has changed the stored login.
  function delayedUnauthorized() {
    let release!: () => void;
    const released = new Promise<void>((resolve) => { release = resolve; });
    server.use(http.get('*/api/auth/me', async () => { await released; return unauthorized(); }));
    return release;
  }

  it('does not erase a newer login when a 401 for an old token arrives late', async () => {
    storeAccessToken('old');
    const release = delayedUnauthorized();

    const pending = authFetch('/api/auth/me');
    storeAccessToken('newer');
    release();
    await pending;

    expect(getStoredAccessToken()).toBe('newer');
    expect(assign).not.toHaveBeenCalled();
  });

  it('still opens the sign-in page when another tab signed out before the late 401', async () => {
    storeAccessToken('old');
    const release = delayedUnauthorized();

    const pending = authFetch('/api/auth/me');
    clearAccessToken();
    release();
    await pending;

    expect(assign).toHaveBeenCalledWith('/auth');
  });
});
