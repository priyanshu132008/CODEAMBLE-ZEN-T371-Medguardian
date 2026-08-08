'use client';

import { useRouter } from 'next/navigation';
import { LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Sleek "Log Out" control for the authenticated portals.
 *
 * Clears the `medguardian_auth` + `medguardian_role` cookies (expiring them
 * with max-age=0) and the persisted localStorage session, then redirects to
 * `/login`. This invalidates the RBAC proxy gate immediately — the next
 * request to `/patient` or `/admin` bounces to login.
 */
export default function LogoutButton({ className }: { className?: string }) {
  const router = useRouter();

  const handleLogout = () => {
    if (typeof window !== 'undefined') {
      document.cookie = 'medguardian_auth=; path=/; max-age=0; SameSite=Lax';
      document.cookie = 'medguardian_role=; path=/; max-age=0; SameSite=Lax';
      try {
        localStorage.removeItem('medguardian_session');
      } catch {
        /* ignore */
      }
    }
    router.push('/login');
  };

  return (
    <button
      type="button"
      onClick={handleLogout}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition-all duration-200 hover:border-rose-300 hover:text-rose-600',
        className
      )}
      title="Sign out of MedGuardian"
    >
      <LogOut className="h-3.5 w-3.5" />
      Log Out
    </button>
  );
}