import { createHash } from 'node:crypto';

import { cookies } from 'next/headers';

import { DEV_ACCESS_COOKIE_NAME, getAccessGatePassword } from '@/lib/dev-access';

function hashAccessGatePassword(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

export async function hasAccessGateCookie(): Promise<boolean> {
  const configuredPassword = getAccessGatePassword();
  if (!configuredPassword) {
    return true;
  }

  const cookieStore = await cookies();
  const cookieValue = cookieStore.get(DEV_ACCESS_COOKIE_NAME)?.value;
  if (!cookieValue) {
    return false;
  }

  return cookieValue === hashAccessGatePassword(configuredPassword);
}
