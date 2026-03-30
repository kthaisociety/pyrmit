import { cookies } from 'next/headers';

import { DEV_ACCESS_COOKIE_NAME } from '@/lib/dev-access';

export async function hasAccessGateCookie(): Promise<boolean> {
  const cookieStore = await cookies();
  return Boolean(cookieStore.get(DEV_ACCESS_COOKIE_NAME)?.value);
}
