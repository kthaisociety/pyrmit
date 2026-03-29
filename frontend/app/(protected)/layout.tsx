import { redirect } from 'next/navigation';

import { hasAccessGateCookie } from '@/lib/access-gate-server';

export default async function ProtectedLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const hasAccess = await hasAccessGateCookie();
  if (!hasAccess) {
    redirect('/dev-access');
  }

  return children;
}
