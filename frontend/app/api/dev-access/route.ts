import { NextResponse } from 'next/server';

import { DEV_ACCESS_COOKIE_NAME, hashDevAccessPassword } from '@/lib/dev-access';

export async function POST(request: Request) {
  const configuredPassword = process.env.DEV_ACCESS_PASSWORD?.trim();
  if (!configuredPassword) {
    return NextResponse.json(
      { detail: 'Development access is not configured.' },
      { status: 503 },
    );
  }

  const body = (await request.json().catch(() => null)) as { password?: string } | null;
  const submittedPassword = body?.password?.trim() ?? '';
  if (!submittedPassword) {
    return NextResponse.json(
      { detail: 'Password is required.' },
      { status: 400 },
    );
  }

  const [expectedHash, submittedHash] = await Promise.all([
    hashDevAccessPassword(configuredPassword),
    hashDevAccessPassword(submittedPassword),
  ]);

  if (submittedHash !== expectedHash) {
    return NextResponse.json(
      { detail: 'Invalid development access password.' },
      { status: 401 },
    );
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: DEV_ACCESS_COOKIE_NAME,
    value: expectedHash,
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 12,
  });

  return response;
}
