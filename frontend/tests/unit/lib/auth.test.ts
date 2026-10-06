// Unit tests for lib/auth.ts.
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';

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

  it('does not redirect on a 401 for any other reason', async () => {
    const assign = vi.fn();
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign });
    server.use(
      http.get('*/api/auth/me', () =>
        HttpResponse.json({ detail: 'Invalid token' }, { status: 401 }),
      ),
    );

    await authFetch('/api/auth/me');

    expect(assign).not.toHaveBeenCalled();
  });
});
