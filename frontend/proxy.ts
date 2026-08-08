import { NextResponse, type NextRequest } from 'next/server';

/**
 * Route protection + strict role-based access control (RBAC) edge gate.
 *
 * Two cookies set by the Auth Gateway on sign-in drive the gate:
 *   - `medguardian_auth`  (presence → authenticated)
 *   - `medguardian_role`  ('patient' | 'admin')
 *
 * Rules:
 *   /admin   → requires auth + role 'admin'. A patient is bounced to /patient.
 *   /patient → requires auth + role 'patient'. An admin is bounced to /admin.
 *   Missing/unknown role → forced back to /login (re-establish the session).
 *   Unauthenticated → /login?redirect=<original-path>.
 *
 * The role firewall is enforced at the edge so a logged-in patient can never
 * reach /admin and a logged-in admin can never reach /patient, regardless of
 * client-side navigation. Bounce redirects carry no `redirect` param (so a
 * cross-role user isn't funnelled back into the portal they tried to breach).
 *
 * SECURITY NOTE: presence/role cookies are set client-side on login. For
 * full server-verified auth, upgrade login to set an httpOnly cookie issued by
 * the Supabase backend and verify it here against `/api/auth/me` — the cookie
 * contract stays the same, so the upgrade is contained to the login handler.
 *
 * (Next.js 16 renamed the `middleware.ts` convention to `proxy.ts`; the
 * function is exported as `proxy` accordingly.)
 */

type Role = 'patient' | 'admin';

function targetFor(pathname: string): Role | null {
  if (pathname === '/patient' || pathname.startsWith('/patient/')) return 'patient';
  if (pathname === '/admin' || pathname.startsWith('/admin/')) return 'admin';
  return null;
}

function isRole(v: string | undefined): v is Role {
  return v === 'patient' || v === 'admin';
}

function redirectToLogin(request: NextRequest, withRedirect: boolean) {
  const url = request.nextUrl.clone();
  url.pathname = '/login';
  if (withRedirect) url.searchParams.set('redirect', request.nextUrl.pathname);
  else url.searchParams.delete('redirect');
  return NextResponse.redirect(url);
}

function redirectToPortal(request: NextRequest, role: Role) {
  // Bounce a cross-role user to their OWN portal — no ?redirect, so they
  // can't be funnelled back into the portal they tried to breach.
  const url = request.nextUrl.clone();
  url.pathname = role === 'admin' ? '/admin' : '/patient';
  url.searchParams.delete('redirect');
  return NextResponse.redirect(url);
}

export function proxy(request: NextRequest) {
  const target = targetFor(request.nextUrl.pathname);
  if (!target) return NextResponse.next();

  const auth = request.cookies.get('medguardian_auth')?.value;
  const role = request.cookies.get('medguardian_role')?.value;

  // Not authenticated → login (remember where they were headed).
  if (!auth) return redirectToLogin(request, true);

  // Authenticated but role cookie missing/unknown → force re-auth.
  if (!isRole(role)) return redirectToLogin(request, true);

  // Role firewall: wrong role → bounce to their own portal.
  if (role !== target) return redirectToPortal(request, role);

  return NextResponse.next();
}

export const config = {
  // Only run the gate on the protected portals (and their sub-paths); everything
  // else (landing, login, manifest, static assets) is untouched.
  matcher: ['/patient/:path*', '/admin/:path*'],
};