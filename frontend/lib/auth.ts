const ACCESS_TOKEN_KEY = 'pyrmit_access_token';

// Development trade-off: storing the bearer token in localStorage keeps the
// frontend simple, but any XSS bug would make the token readable by scripts.
export function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function storeAccessToken(token: string) {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAccessToken() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function getAuthHeaders(headers?: HeadersInit): Headers {
  const nextHeaders = new Headers(headers);
  const token = getStoredAccessToken();
  if (token) {
    nextHeaders.set('Authorization', `Bearer ${token}`);
  }
  return nextHeaders;
}

function redirectToAccessGate() {
  if (typeof window === 'undefined') {
    return;
  }

  if (window.location.pathname === '/dev-access') {
    return;
  }

  const next = `${window.location.pathname}${window.location.search}`;
  const nextParam = next && next !== '/' ? `?next=${encodeURIComponent(next)}` : '';
  window.location.assign(`/dev-access${nextParam}`);
}

export async function authFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const response = await fetch(input, {
    ...init,
    credentials: 'include',
    headers: getAuthHeaders(init.headers),
  });

  if (response.status === 401 || response.status === 403) {
    const clone = response.clone();
    const data = await clone.json().catch(() => null);
    if (data?.detail === 'Access password required') {
      redirectToAccessGate();
    }
  }

  return response;
}
