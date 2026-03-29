const encoder = new TextEncoder();

export const DEV_ACCESS_COOKIE_NAME = 'dev_access_granted';

export async function hashDevAccessPassword(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}
