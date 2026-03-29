import { NextRequest, NextResponse } from 'next/server';

import { DEV_ACCESS_COOKIE_NAME, hashDevAccessPassword } from '@/lib/dev-access';

const PUBLIC_FILE_PATTERN = /\.[^/]+$/;

export async function middleware(request: NextRequest) {
  const configuredPassword = process.env.DEV_ACCESS_PASSWORD?.trim();
  if (!configuredPassword) {
    return NextResponse.next();
  }

  const { pathname, search } = request.nextUrl;
  const isBypassedPath =
    pathname === '/dev-access' ||
    pathname.startsWith('/api/dev-access') ||
    pathname.startsWith('/_next') ||
    pathname === '/favicon.ico' ||
    PUBLIC_FILE_PATTERN.test(pathname);

  const expectedHash = await hashDevAccessPassword(configuredPassword);
  const hasAccess = request.cookies.get(DEV_ACCESS_COOKIE_NAME)?.value === expectedHash;

  if (hasAccess && pathname === '/dev-access') {
    return NextResponse.redirect(new URL('/', request.url));
  }

  if (hasAccess || isBypassedPath) {
    return NextResponse.next();
  }

  const redirectUrl = new URL('/dev-access', request.url);
  redirectUrl.searchParams.set('next', `${pathname}${search}`);
  return NextResponse.redirect(redirectUrl);
}

export const config = {
  matcher: '/:path*',
};
