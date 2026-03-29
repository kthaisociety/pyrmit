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

export async function authFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return fetch(input, {
    ...init,
    credentials: 'include',
    headers: getAuthHeaders(init.headers),
  });
}
