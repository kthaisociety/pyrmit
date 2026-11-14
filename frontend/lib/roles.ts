// User roles (issue #112). The backend checks the role on every sensitive route; the page only hides what the role
// can't use, so these helpers are for display, never for access control.
export type Role = 'owner' | 'developer' | 'user';

export const ROLES: Role[] = ['owner', 'developer', 'user'];

export interface CurrentUser {
  id: string;
  name: string;
  email: string;
  role?: Role; // missing from an older backend: treated as a plain user
}

export function isOwner(user: { role?: Role } | null | undefined): boolean {
  return user?.role === 'owner';
}

// Owners and developers: the work tools (benchmark runs, ingestion) and the admin views
export function isStaff(user: { role?: Role } | null | undefined): boolean {
  return user?.role === 'owner' || user?.role === 'developer';
}
